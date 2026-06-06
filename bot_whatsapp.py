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

app = Flask(__name__)

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
EVOLUTION_API_URL = "https://evolution-api-production-02e0.up.railway.app"
EVOLUTION_API_KEY = "ed3c5b11b073e0167bebf4fa37e2989a57828b2ae284d6bc45f0ee859b4a033c"
EVOLUTION_INSTANCE = "CRCALDEIRARIA"
GOOGLE_SHEET_ID = "10-DezJakw5Qn7zZdC30mWqejZq7F3_vpV4Qg9qbmKFo"

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

def carregar_planilha():
    try:
        url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv&gid=746253589"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df = df.dropna(how="all")
        df = df.head(300)
        return df.to_string(index=False, max_rows=300)
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
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return resposta.content[0].text

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        print(f"Webhook recebido: {json.dumps(data)[:500]}")

        if "query" in data and "inputs" in data:
            inputs = data.get("inputs", {})
            from_me = inputs.get("fromMe", False)
            if from_me:
                return jsonify({"output": ""})
            mensagem = data.get("query", "")
            if not mensagem:
                return jsonify({"output": ""})
            print(f"Mensagem recebida: {mensagem}")
            dados = carregar_planilha()
            resposta = consultar_claude(mensagem, dados)
            print(f"Resposta: {resposta[:100]}")
            return jsonify({"output": resposta})

        numero = None
        mensagem = None
        from_me = False

        if "message" in data and "conversation" in data.get("message", {}):
            mensagem = data["message"]["conversation"]
            numero = data.get("key", {}).get("remoteJid", "")
            from_me = data.get("key", {}).get("fromMe", False)
        elif "data" in data:
            d = data["data"]
            from_me = d.get("key", {}).get("fromMe", False)
            numero = d.get("key", {}).get("remoteJid", "")
            msg = d.get("message", {})
            mensagem = msg.get("conversation") or msg.get("extendedTextMessage", {}).get("text", "")

        if from_me:
            return jsonify({"status": "ok"})

        if not mensagem or not numero:
            print(f"Formato nao reconhecido. Data: {data}")
            return jsonify({"status": "ok"})

        print(f"Mensagem recebida de {numero}: {mensagem}")
        dados = carregar_planilha()
        resposta = consultar_claude(mensagem, dados)
        print(f"Resposta: {resposta[:100]}")
        enviar_mensagem_whatsapp(numero, resposta)
        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Erro no webhook: {e}")
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
