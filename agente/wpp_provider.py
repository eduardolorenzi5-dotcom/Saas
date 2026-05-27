"""
wpp_provider.py — Camada de abstração para envio de mensagens WhatsApp.

Para trocar de provedor, basta setar a variável de ambiente:
  WPP_PROVIDER=evolution  (padrão atual)
  WPP_PROVIDER=meta       (API oficial Meta/WhatsApp Cloud)

Variáveis necessárias por provedor:

  Evolution API (atual):
    EVOLUTION_URL, EVOLUTION_KEY, EVOLUTION_INSTANCE

  Meta Cloud API (oficial):
    WHATSAPP_TOKEN       — token de acesso permanente (System User)
    WHATSAPP_PHONE_ID    — ID do número de telefone no Meta
    WHATSAPP_VERIFY_TOKEN — token de verificação do webhook (você define)
"""

import os
import json
import logging
import requests

# ── Configurações ────────────────────────────────────────────────────────────
WPP_PROVIDER = os.environ.get("WPP_PROVIDER", "evolution").lower()

# Evolution API
EVOLUTION_URL      = os.environ.get("EVOLUTION_URL", "")
EVOLUTION_KEY      = os.environ.get("EVOLUTION_KEY", "")
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "")

# Meta Cloud API
WHATSAPP_TOKEN        = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID     = os.environ.get("WHATSAPP_PHONE_ID", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "controla_facil_verify")
META_API_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"


# ── Envio de texto ───────────────────────────────────────────────────────────

def send_text(fone: str, mensagem: str) -> bool:
    """Envia mensagem de texto. Retorna True se enviou com sucesso."""
    fone = _limpar_fone(fone)
    if not fone:
        return False

    if WPP_PROVIDER == "meta":
        return _meta_send_text(fone, mensagem)
    else:
        return _evolution_send_text(fone, mensagem)


def _evolution_send_text(fone: str, mensagem: str) -> bool:
    if not EVOLUTION_KEY:
        print(f"[WPP-DEV → {fone}] {mensagem}")
        return True
    try:
        r = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}",
            headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
            json={"number": fone, "text": mensagem},
            timeout=10
        )
        return r.status_code < 300
    except Exception as e:
        logging.error(f"[WPP-EVOLUTION] Erro send_text: {e}")
        return False


def _meta_send_text(fone: str, mensagem: str) -> bool:
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        logging.error("[WPP-META] WHATSAPP_TOKEN ou WHATSAPP_PHONE_ID não configurado")
        return False
    try:
        r = requests.post(
            META_API_URL,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "to": fone,
                "type": "text",
                "text": {"body": mensagem, "preview_url": False}
            },
            timeout=10
        )
        if r.status_code >= 300:
            logging.error(f"[WPP-META] Erro send_text {r.status_code}: {r.text}")
        return r.status_code < 300
    except Exception as e:
        logging.error(f"[WPP-META] Erro send_text: {e}")
        return False


# ── Envio de imagem (URL pública) ────────────────────────────────────────────

def send_image_url(fone: str, image_url: str, caption: str = "") -> bool:
    """Envia imagem a partir de URL pública."""
    fone = _limpar_fone(fone)
    if not fone:
        return False

    if WPP_PROVIDER == "meta":
        return _meta_send_image_url(fone, image_url, caption)
    else:
        return _evolution_send_image_url(fone, image_url, caption)


def _evolution_send_image_url(fone: str, image_url: str, caption: str) -> bool:
    if not EVOLUTION_KEY:
        return False
    try:
        r = requests.post(
            f"{EVOLUTION_URL}/message/sendMedia/{EVOLUTION_INSTANCE}",
            headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
            json={
                "number": fone,
                "mediatype": "image",
                "media": image_url,
                "caption": caption,
            },
            timeout=15
        )
        return r.status_code < 300
    except Exception as e:
        logging.error(f"[WPP-EVOLUTION] Erro send_image_url: {e}")
        return False


def _meta_send_image_url(fone: str, image_url: str, caption: str) -> bool:
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        return False
    try:
        body = {
            "messaging_product": "whatsapp",
            "to": fone,
            "type": "image",
            "image": {"link": image_url}
        }
        if caption:
            body["image"]["caption"] = caption
        r = requests.post(
            META_API_URL,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json=body,
            timeout=15
        )
        if r.status_code >= 300:
            logging.error(f"[WPP-META] Erro send_image_url {r.status_code}: {r.text}")
        return r.status_code < 300
    except Exception as e:
        logging.error(f"[WPP-META] Erro send_image_url: {e}")
        return False


# ── Envio de imagem (base64) ─────────────────────────────────────────────────

def send_image_b64(fone: str, imagem_b64: str, caption: str = "", filename: str = "imagem.png") -> bool:
    """Envia imagem em base64. Meta API exige upload prévio — faz upload automático."""
    fone = _limpar_fone(fone)
    if not fone:
        return False

    if WPP_PROVIDER == "meta":
        # Meta não aceita base64 direto — precisa fazer upload para obter media_id
        media_id = _meta_upload_media_b64(imagem_b64, filename)
        if not media_id:
            return False
        return _meta_send_image_id(fone, media_id, caption)
    else:
        return _evolution_send_image_b64(fone, imagem_b64, caption, filename)


def _evolution_send_image_b64(fone: str, imagem_b64: str, caption: str, filename: str) -> bool:
    if not EVOLUTION_KEY:
        return False
    try:
        r = requests.post(
            f"{EVOLUTION_URL}/message/sendMedia/{EVOLUTION_INSTANCE}",
            headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
            json={
                "number": fone,
                "mediatype": "image",
                "mimetype": "image/png",
                "caption": caption,
                "media": imagem_b64,
                "fileName": filename,
            },
            timeout=20
        )
        return r.status_code < 300
    except Exception as e:
        logging.error(f"[WPP-EVOLUTION] Erro send_image_b64: {e}")
        return False


def _meta_upload_media_b64(imagem_b64: str, filename: str) -> str | None:
    """Faz upload de mídia base64 para Meta e retorna media_id."""
    import base64
    try:
        img_bytes = base64.b64decode(imagem_b64)
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/media",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            files={"file": (filename, img_bytes, "image/png")},
            data={"messaging_product": "whatsapp"},
            timeout=30
        )
        if r.status_code < 300:
            return r.json().get("id")
        logging.error(f"[WPP-META] Erro upload media: {r.text}")
        return None
    except Exception as e:
        logging.error(f"[WPP-META] Erro upload media: {e}")
        return None


def _meta_send_image_id(fone: str, media_id: str, caption: str) -> bool:
    try:
        body = {
            "messaging_product": "whatsapp",
            "to": fone,
            "type": "image",
            "image": {"id": media_id}
        }
        if caption:
            body["image"]["caption"] = caption
        r = requests.post(
            META_API_URL,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json=body,
            timeout=15
        )
        return r.status_code < 300
    except Exception as e:
        logging.error(f"[WPP-META] Erro send_image_id: {e}")
        return False


# ── Parser de webhook ─────────────────────────────────────────────────────────

def parse_webhook(payload: dict) -> dict | None:
    """
    Normaliza o payload do webhook para um formato único:
    {
        "fone": "5511999999999",
        "msg_id": "...",
        "tipo": "text" | "audio" | "image" | "document",
        "texto": "...",          # para tipo text
        "media_url": "...",      # para audio/image (Meta)
        "media_b64": "...",      # para audio/image (Evolution)
        "caption": "...",        # legenda da imagem
        "raw": {...}             # payload original
    }
    Retorna None se não for uma mensagem processável.
    """
    if WPP_PROVIDER == "meta":
        return _parse_meta_webhook(payload)
    else:
        return _parse_evolution_webhook(payload)


def _parse_evolution_webhook(payload: dict) -> dict | None:
    """Parser para Evolution API — mantém compatibilidade com código atual."""
    # Formato Typebot (inputs)
    if "inputs" in payload:
        inputs = payload.get("inputs", {})
        contact = payload.get("contact", {})
        fone = (inputs.get("remoteJid", "").replace("@s.whatsapp.net", "") or
                str(contact.get("id", "")).replace("@s.whatsapp.net", ""))
        msg_id = payload.get("sessionId", "") or inputs.get("messageId", "")
        tipo_input = inputs.get("type", "text")

        if tipo_input == "audio":
            return {"fone": fone, "msg_id": msg_id, "tipo": "audio",
                    "media_b64": inputs.get("data", {}).get("base64", ""),
                    "texto": "", "raw": payload}
        elif tipo_input == "image":
            return {"fone": fone, "msg_id": msg_id, "tipo": "image",
                    "media_b64": inputs.get("data", {}).get("base64", ""),
                    "caption": inputs.get("data", {}).get("caption", ""),
                    "texto": "", "raw": payload}
        else:
            texto = (inputs.get("data", {}).get("text", "") or
                     inputs.get("data", {}).get("message", "") or str(inputs))
            return {"fone": fone, "msg_id": msg_id, "tipo": "text",
                    "texto": texto, "raw": payload}

    # Formato direto (data)
    data = payload.get("data", {})
    if not data:
        return None
    key = data.get("key", {})
    fone = key.get("remoteJid", "").replace("@s.whatsapp.net", "")
    msg_id = key.get("id", "")
    msg = data.get("message", {})
    msg_type = data.get("messageType", "")

    if msg_type in ("audioMessage", "pttMessage"):
        return {"fone": fone, "msg_id": msg_id, "tipo": "audio",
                "media_b64": data.get("message", {}).get("base64", ""),
                "texto": "", "raw": payload}
    elif msg_type == "imageMessage":
        img = msg.get("imageMessage", {})
        return {"fone": fone, "msg_id": msg_id, "tipo": "image",
                "media_b64": data.get("message", {}).get("base64", ""),
                "caption": img.get("caption", ""),
                "texto": "", "raw": payload}
    else:
        texto = (msg.get("conversation") or
                 msg.get("extendedTextMessage", {}).get("text", "") or "")
        if not texto:
            return None
        return {"fone": fone, "msg_id": msg_id, "tipo": "text",
                "texto": texto, "raw": payload}


def _parse_meta_webhook(payload: dict) -> dict | None:
    """Parser para Meta Cloud API."""
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        fone = msg.get("from", "")
        msg_id = msg.get("id", "")
        msg_type = msg.get("type", "text")

        if msg_type == "text":
            return {"fone": fone, "msg_id": msg_id, "tipo": "text",
                    "texto": msg.get("text", {}).get("body", ""), "raw": payload}

        elif msg_type == "audio":
            audio_id = msg.get("audio", {}).get("id", "")
            media_url = _meta_get_media_url(audio_id)
            return {"fone": fone, "msg_id": msg_id, "tipo": "audio",
                    "media_url": media_url, "texto": "", "raw": payload}

        elif msg_type == "image":
            image_id = msg.get("image", {}).get("id", "")
            caption = msg.get("image", {}).get("caption", "")
            media_url = _meta_get_media_url(image_id)
            return {"fone": fone, "msg_id": msg_id, "tipo": "image",
                    "media_url": media_url, "caption": caption,
                    "texto": "", "raw": payload}

        return None
    except Exception as e:
        logging.error(f"[WPP-META] Erro parse_webhook: {e}")
        return None


def _meta_get_media_url(media_id: str) -> str:
    """Obtém a URL de download de uma mídia pelo ID (Meta API)."""
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10
        )
        return r.json().get("url", "")
    except Exception as e:
        logging.error(f"[WPP-META] Erro get_media_url: {e}")
        return ""


def download_media_meta(media_url: str) -> bytes | None:
    """Baixa mídia da Meta API (requer header Authorization)."""
    try:
        r = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=30
        )
        return r.content if r.status_code == 200 else None
    except Exception as e:
        logging.error(f"[WPP-META] Erro download_media: {e}")
        return None


# ── Verificação de webhook Meta ───────────────────────────────────────────────

def verify_meta_webhook(args: dict) -> tuple[str, int]:
    """
    Verifica o challenge do webhook da Meta.
    Usar na rota GET /webhook/whatsapp quando WPP_PROVIDER=meta.

    Exemplo no Flask:
        from agente.wpp_provider import verify_meta_webhook
        @app.route("/webhook/whatsapp", methods=["GET"])
        def wh_verify():
            response, status = verify_meta_webhook(request.args)
            return response, status
    """
    mode      = args.get("hub.mode")
    token     = args.get("hub.verify_token")
    challenge = args.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logging.info("[WPP-META] Webhook verificado com sucesso")
        return challenge, 200
    return "Forbidden", 403


# ── Utilitários ───────────────────────────────────────────────────────────────

def _limpar_fone(fone: str) -> str:
    """Remove caracteres não numéricos do número."""
    return "".join(d for d in (fone or "") if d.isdigit())


def provedor_ativo() -> str:
    return WPP_PROVIDER
