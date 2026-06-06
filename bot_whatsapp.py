"""
Bot WhatsApp - CR Caldeiraria
Responde perguntas sobre a planilha de Acompanhamento e Controle da Produção
"""
from flask import Flask, request, jsonify
import anthropic
import pandas as pd
import requests
import json
import os
import io
import re
from datetime import datetime

app = Flask(__name__)
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
EVOLUTION_API_URL = "https://evolution-api-production-02e0.up.railway.app"
EVOLUTION_API_KEY = "ed3c5b11b073e0167bebf4fa37e2989a57828b2ae284d6bc45f0ee859b4a033c"
EVOLUTION_INSTANCE = "CRCALDEIRARIA"
GOOGLE_SHEET_ID = "10-DezJakw5Qn7zZdC30mWqejZq7F3_vpV4Qg9qbmKFo"
GOOGLE_SHEET_GID = "306020472"

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

def carregar_planilha_completa():
    url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv&gid={GOOGLE_SHEET_GID}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df = df.dropna(how="all")
    return df

def extrair_mes_ano(pergunta):
    meses = {
        "janeiro": "01", "fevereiro": "02", "marco": "03", "abril": "04",
        "maio": "05", "junho": "06", "julho": "07", "agosto": "08",
        "setembro": "09", "outubro": "10", "novembro": "11", "dezembro": "12",
        "jan": "01", "fev": "02", "mar": "03", "abr": "04",
        "mai": "05", "jun": "06", "jul": "07", "ago": "08",
        "set": "09", "out": "10", "nov": "11", "dez": "12"
    }
    pergunta_lower = pergunta.lower()
    mes_encontrado = None
    for nome, num in meses.items():
        if nome in pergunta_lower:
            mes_encontrado = num
            break
    match = re.search(r'(\d{1,2})[/\-](\d{4})', pergunta)
    if match:
        return match.group(1).zfill(2), match.group(2)
    match_ano = re.search(r'\b(202\d)\b', pergunta)
    ano = match_ano.group(1) if match_ano else str(datetime.now().year)
    return mes_encontrado, ano

def filtrar_dados(df, pergunta):
    pergunta_upper = pergunta.upper()
    palavras = re.findall(r'\b[A-Z0-9]{3,}\b', pergunta_upper)
    df_filtrado = pd.DataFrame()
    colunas_texto = [c for c in df.columns if df[c].dtype == object]
    encontrou = False

    # Filtro por data de vencimento
    col_vencimento = None
    for col in df.columns:
        if "vencimento" in col.lower() or "venc" in col.lower():
            col_vencimento = col
            break

    mes, ano = extrair_mes_ano(pergunta)
    if col_vencimento and mes:
        df[col_vencimento] = pd.to_datetime(df[col_vencimento], errors="coerce", dayfirst=True)
        mask_data = (df[col_vencimento].dt.month == int(mes)) & (df[col_vencimento].dt.year == int(ano))
        if mask_data.any():
            df_filtrado = pd.concat([df_filtrado, df[mask_data]]).drop_duplicates()
            encontrou = True

    # Filtro por palavras-chave
    for palavra in palavras:
        if len(palavra) < 3:
            continue
        for col in colunas_texto:
            mask = df[col].astype(str).str.upper().str.contains(palavra, na=False)
            if mask.any():
                df_filtrado = pd.concat([df_filtrado, df[mask]]).drop_duplicates()
                encontrou = True

    # Se não encontrou nada específico, retorna todas as linhas (até 500)
    if not encontrou:
        df_filtrado = df.head(500)

    if len(df_filtrado) > 200:
        df_filtrado = df_filtrado.head(200)

    return df_filtrado

def carregar_dados(pergunta):
    try:
        df = carregar_planilha_completa()
        for col in ["Status", "STATUS", "status"]:
            if col in df.columns:
                df = df[~df[col].astype(str).str.contains("Expedido|EXPEDIDO|expedido", na=False)]
                break
        df_filtrado = filtrar_dados(df, pergunta)
        return df_filtrado.to_string(index=False)
    except Exception as e:
        return f"Erro ao carregar planilha: {e}"

def enviar_mensagem_whatsapp(numero, mensagem):
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"number": numero, "text": mensagem}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"Envio status: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False

def consultar_claude(pergunta, dados_planilha):
    prompt = f"""Você é um assistente da empresa CR Caldeiraria.
Abaixo estão os dados de acompanhamento e controle da produção da empresa.
Responda a pergunta do usuário de forma clara e objetiva em português.
Se a informação não estiver nos dados, diga que não encontrou.

DADOS DA PLANILHA:
{dados_planilha}

PERGUNTA DO USUÁRIO:
{pergunta}"""
    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    return resposta.content[0].text

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        print(f"Webhook recebido: {json.dumps(data)[:300]}")
        mensagem = None
        numero = None
        from_me = False

        if "query" in data and "inputs" in data:
            inputs = data.get("inputs", {})
            from_me = inputs.get("fromMe", False)
            if from_me:
                return jsonify({"output": ""})
            mensagem = data.get("query", "")
            if not mensagem:
                return jsonify({"output": ""})
            print(f"Mensagem: {mensagem}")
            dados = carregar_dados(mensagem)
            resposta = consultar_claude(mensagem, dados)
            print(f"Resposta: {resposta[:100]}")
            return jsonify({"output": resposta})

        if "event" in data and data.get("event") == "messages.upsert":
            d = data.get("data", {})
            from_me = d.get("key", {}).get("fromMe", False)
            if from_me:
                return jsonify({"status": "ok"})
            numero = d.get("key", {}).get("remoteJid", "")
            msg = d.get("message", {})
            mensagem = (msg.get("conversation") or
                       msg.get("extendedTextMessage", {}).get("text", ""))
        elif "data" in data:
            d = data["data"]
            from_me = d.get("key", {}).get("fromMe", False)
            if from_me:
                return jsonify({"status": "ok"})
            numero = d.get("key", {}).get("remoteJid", "")
            msg = d.get("message", {})
            mensagem = (msg.get("conversation") or
                       msg.get("extendedTextMessage", {}).get("text", ""))

        if not mensagem or not numero:
            print(f"Sem mensagem/número.")
            return jsonify({"status": "ok"})

        print(f"Mensagem de {numero}: {mensagem}")
        dados = carregar_dados(mensagem)
        resposta = consultar_claude(mensagem, dados)
        print(f"Resposta: {resposta[:100]}")
        enviar_mensagem_whatsapp(numero, resposta)
        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Erro: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Bot CR Caldeiraria rodando!"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Bot iniciando na porta {port}...")
    app.run(host="0.0.0.0", port=port)
