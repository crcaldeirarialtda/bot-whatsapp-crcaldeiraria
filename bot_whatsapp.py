"""
Bot WhatsApp - CR Caldeiraria
Responde perguntas sobre a planilha de Acompanhamento e Controle da Produção
Suporte a envio de desenhos em PDF via Google Drive
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
GOOGLE_SHEET_NAME = "Producao"
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbyGVTZz5IxHUHadZEQu49_iAsv6ztPZ_u1wbtR1Wj9o6C-zcStPEWtLBhTGcKmTBkpc/exec"

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

def carregar_planilha_completa():
    url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv&sheet={GOOGLE_SHEET_NAME}"
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

STOPWORDS = {
    "QUAIS", "QUAL", "TODOS", "TODAS", "PARA", "COM", "SEM", "POR", "NUM", "UMA",
    "ESTA", "ESTE", "ESSA", "ESSE", "SOBRE", "COMO", "QUANDO", "ONDE", "TEM",
    "INFORMACOES", "INFORMACAO", "STATUS", "SITUACAO", "VENCE", "VENCIMENTO",
    "PEDIDO", "PEDIDOS", "CLIENTE", "CLIENTES", "DATA", "PRAZO", "LISTA",
    "MEU", "MINHA", "VER", "QUERO", "MANDA", "ENVIA", "BUSCA", "BUSCAR",
    "HAV", "TEVE", "SERA", "SABE", "DIGA", "FALA", "SHOW", "NAO", "SIM",
    "PRODUCAO", "BOT", "OLA", "BOM", "DIA", "TARDE", "NOITE"
}

def filtrar_dados(df, pergunta):
    pergunta_upper = pergunta.upper()
    palavras = re.findall(r'\b[A-Z0-9]{3,}\b', pergunta_upper)
    palavras = [p for p in palavras if p not in STOPWORDS and len(p) >= 3]

    df_filtrado = pd.DataFrame()
    colunas_texto = [c for c in df.columns if str(df[c].dtype) in ('object', 'string', 'str')]
    encontrou = False

    col_vencimento = None
    for col in df.columns:
        if "vencimento" in col.lower() or "venc" in col.lower():
            col_vencimento = col
            break

    mes, ano = extrair_mes_ano(pergunta)

    for palavra in palavras:
        for col in colunas_texto:
            mask = df[col].astype(str).str.upper().str.contains(palavra, na=False)
            if mask.any():
                df_filtrado = pd.concat([df_filtrado, df[mask]]).drop_duplicates()
                encontrou = True

    if col_vencimento and mes:
        df[col_vencimento] = pd.to_datetime(df[col_vencimento], errors="coerce", dayfirst=True)
        mask_data = (df[col_vencimento].dt.month == int(mes)) & (df[col_vencimento].dt.year == int(ano))
        if encontrou:
            df_filtrado[col_vencimento] = pd.to_datetime(df_filtrado[col_vencimento], errors="coerce", dayfirst=True)
            mask_data2 = (df_filtrado[col_vencimento].dt.month == int(mes)) & (df_filtrado[col_vencimento].dt.year == int(ano))
            if mask_data2.any():
                df_filtrado = df_filtrado[mask_data2]
        else:
            if mask_data.any():
                df_filtrado = df[mask_data]
                encontrou = True

    if not encontrou:
        df_filtrado = df.head(50)

    if len(df_filtrado) > 100:
        df_filtrado = df_filtrado.head(100)

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

def detectar_pedido_desenho(pergunta):
    palavras_desenho = ["desenho", "pdf", "planta", "dwg", "arquivo", "documento",
                        "me manda", "me envia", "me envie", "quero ver", "ver o"]
    pergunta_lower = pergunta.lower()
    return any(p in pergunta_lower for p in palavras_desenho)

def extrair_codigo_peca(pergunta):
    padroes = [
        r'\b[A-Z0-9]{3,}[-_][A-Z0-9]+(?:[-_][A-Z0-9]+)*\b',
        r'\b[A-Z]{2,}[0-9]{4,}[A-Z0-9-]*\b',
    ]
    pergunta_upper = pergunta.upper()
    for padrao in padroes:
        matches = re.findall(padrao, pergunta_upper)
        if matches:
            return matches[0]
    return None

def buscar_pdf_drive(codigo_peca):
    try:
        resp = requests.get(APPS_SCRIPT_URL, params={"codigo": codigo_peca}, timeout=15)
        resp.raise_for_status()
        resultado = resp.json()
        if resultado.get("found"):
            return resultado["fileId"], resultado["name"]
        return None, None
    except Exception as e:
        print(f"Erro ao buscar PDF no Drive: {e}")
        return None, None

def enviar_pdf_whatsapp(numero, file_id, nome_arquivo):
    url_pdf = f"https://drive.google.com/uc?export=download&id={file_id}"
    url = f"{EVOLUTION_API_URL}/message/sendMedia/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {
        "number": numero,
        "mediatype": "document",
        "media": url_pdf,
        "fileName": nome_arquivo,
        "caption": f"Desenho: {nome_arquivo}"
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"Erro ao enviar PDF: {e}")
        return False

def processar_pedido_desenho(numero, mensagem):
    codigo = extrair_codigo_peca(mensagem)
    if not codigo:
        enviar_mensagem_whatsapp(numero, "⚠️ Não consegui identificar o código da peça. Envie o código completo, por exemplo: *GR1G083213-00*")
        return True
    file_id, nome = buscar_pdf_drive(codigo)
    if file_id:
        enviar_mensagem_whatsapp(numero, f"📄 Encontrei o desenho *{nome}*. Enviando...")
        sucesso = enviar_pdf_whatsapp(numero, file_id, nome)
        if not sucesso:
            enviar_mensagem_whatsapp(numero, "❌ Erro ao enviar o arquivo. Tente novamente.")
    else:
        enviar_mensagem_whatsapp(numero, f"❌ Não encontrei desenho para o código *{codigo}*. Verifique se o código está correto.")
    return True

def enviar_mensagem_whatsapp(numero, mensagem):
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"number": numero, "text": mensagem}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False

def consultar_claude(pergunta, dados_planilha):
    dados_truncados = dados_planilha[:6000] if len(dados_planilha) > 6000 else dados_planilha
    prompt = f"""Você é um assistente da CR Caldeiraria. Responda em português, de forma clara e curta.
Se a informação não estiver nos dados, diga que não encontrou.

DADOS:
{dados_truncados}

PERGUNTA: {pergunta}"""
    try:
        resposta = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return resposta.content[0].text
    except Exception as e:
        erro = str(e)
        if "rate_limit" in erro or "429" in erro:
            return "⚠️ Muitas consultas ao mesmo tempo. Aguarde 1 minuto e tente novamente."
        return f"Erro ao consultar: {erro[:100]}"

def processar_mensagem(numero, mensagem):
    if detectar_pedido_desenho(mensagem):
        processar_pedido_desenho(numero, mensagem)
    else:
        dados = carregar_dados(mensagem)
        resposta = consultar_claude(mensagem, dados)
        enviar_mensagem_whatsapp(numero, resposta)

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
            if detectar_pedido_desenho(mensagem):
                return jsonify({"output": "Para receber o desenho, envie o código diretamente no WhatsApp."})
            dados = carregar_dados(mensagem)
            resposta = consultar_claude(mensagem, dados)
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
            return jsonify({"status": "ok"})

        print(f"Mensagem de {numero}: {mensagem}")
        processar_mensagem(numero, mensagem)
        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Erro: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Bot CR Caldeiraria rodando!"})

@app.route("/debug", methods=["GET"])
def debug():
    try:
        df = carregar_planilha_completa()
        clientes = df["Cliente"].dropna().unique().tolist() if "Cliente" in df.columns else []
        voith_rows = df[df["Cliente"].astype(str).str.upper().str.contains("VOITH", na=False)] if "Cliente" in df.columns else pd.DataFrame()
        return jsonify({
            "total_linhas": len(df),
            "colunas": df.columns.tolist(),
            "primeiros_clientes": clientes[:20],
            "voith_encontrado": len(voith_rows),
        })
    except Exception as e:
        return jsonify({"erro": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Bot iniciando na porta {port}...")
    app.run(host="0.0.0.0", port=port)
