import os
import logging
import smtplib
import requests
import threading
from flask import Flask, request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO = "kitay@sync.mylifeorganized.net"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = Flask(__name__)

def tg_send(chat_id, text):
    try:
        requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        log.error(f"tg_send error: {e}")

def tg_get_file_url(file_id):
    r = requests.get(f"{TG_API}/getFile", params={"file_id": file_id}, timeout=10)
    r.raise_for_status()
    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{r.json()['result']['file_path']}"

def transcribe_with_groq(audio_bytes):
    r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": ("voice.ogg", audio_bytes, "audio/ogg")},
        data={"model": "whisper-large-v3-turbo", "language": "ru", "response_format": "text"},
        timeout=60)
    r.raise_for_status()
    return r.text.strip()

def send_email(text):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = "Голосовое сообщение — транскрипция"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.yandex.ru", 465) as srv:
        srv.login(SMTP_USER, SMTP_PASSWORD)
        srv.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())

def process_voice(chat_id, file_id):
    try:
        log.info(f"Получаем файл {file_id}")
        file_url = tg_get_file_url(file_id)
        log.info(f"Скачиваем аудио...")
        audio_bytes = requests.get(file_url, timeout=30).content
        log.info(f"Скачано {len(audio_bytes)} байт, транскрибируем...")
        text = transcribe_with_groq(audio_bytes)
        log.info(f"Транскрипция готова: {text[:50]}")
        if not text:
            tg_send(chat_id, "Не удалось распознать текст.")
            return
        log.info("Отправляем email...")
        send_email(text)
        log.info("Email отправлен!")
        tg_send(chat_id, f"Готово! Письмо отправлено.\n\nТекст:\n{text}")
    except Exception as e:
        log.error(f"Ошибка обработки: {e}", exc_info=True)
        tg_send(chat_id, f"Ошибка: {e}")

def handle_update(update):
    message = update.get("message") or update.get("channel_post")
    if not message:
        return
    chat_id = message["chat"]["id"]
    voice = message.get("voice")
    if not voice:
        tg_send(chat_id, "Привет! Отправь голосовое сообщение.")
        return
    tg_send(chat_id, "Получил! Транскрибирую...")
    # Запускаем обработку в отдельном потоке
    t = threading.Thread(target=process_voice, args=(chat_id, voice["file_id"]))
    t.daemon = True
    t.start()

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    if update:
        handle_update(update)
    return "OK", 200  # Отвечаем Telegram сразу

@app.route("/")
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
