import telebot
from speechkit import *
from validators import *
from yandex_gpt import ask_gpt
from config import TOKEN, LOGS, COUNT_LAST_MSG
from database import create_database, add_message, select_n_last_messages
from telebot.types import KeyboardButton, ReplyKeyboardMarkup
import logging

logging.basicConfig(filename=LOGS, level=logging.ERROR, format="%(asctime)s FILE: %(filename)s IN: %(funcName)s MESSAGE: %(message)s", filemode="w")
bot = telebot.TeleBot(TOKEN)

def menu_keyboard(options):
    buttons = [KeyboardButton(text=option) for option in options]
    keyboard = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(*buttons)
    return keyboard

@bot.message_handler(commands=['debug'])
def debug(message):
    with open("logs.txt", "rb") as f:
        bot.send_document(message.chat.id, f)

@bot.message_handler(commands=['start'])
def start(message):
    user_name = message.from_user.first_name
    bot.send_message(message.chat.id,
                     f"Привет, {user_name}! Я - БОТ-умеющий болтать на любые темы и поддерживать разговор\n"
                     f"Для общения со мной жми /start\n"
                     f"Чтобы протестить функции распознавания речи, жми /stt или /tts\n"
                     f"Если нужна помощь, жми /help",
                     reply_markup=menu_keyboard(["/start", "/stt", "/tts", "/help"]))

@bot.message_handler(commands=['help'])
def help(message):
    user_name = message.from_user.first_name
    bot.send_message(message.chat.id,
                     f"Привет, {user_name}! Я - БОТ-умеющий болтать на любые темы и поддерживать разговор\n"
                     f"Для общения со мной жми /start и отправь вопрос, или с помощью ГС, или текстом.\n"
                     f"Если хочешь протестить функции text to speech или speech to text, жми /stt или /tts",
                     reply_markup=menu_keyboard(["/start", "/stt", "/tts", "/help"]))

@bot.message_handler(commands=['stt'])
def stt_handler(message):
    user_id = message.from_user.id
    bot.send_message(user_id, 'Отправь голосовое сообщение, чтобы я его распознал!')
    bot.register_next_step_handler(message, stt)


def stt(message):
    user_id = message.from_user.id
    # Проверка, что сообщение действительно голосовое
    if not message.voice:
        return
    bot.send_message(user_id, 'Ждём твета...')
    status_check_users, error_message = check_number_of_users(user_id)
    if not status_check_users:
        bot.send_message(user_id, error_message)
        return
    stt_blocks, error_message = is_stt_block_limit(message, message.voice.duration)
    if error_message:
        bot.send_message(user_id, error_message)
        return
    file_id = message.voice.file_id
    file_info = bot.get_file(file_id)
    file = bot.download_file(file_info.file_path)
    status_stt, stt_text = speech_to_text(file)
    if not status_stt:
        bot.send_message(user_id, stt_text)
        return
    add_message(user_id=user_id, full_message=[0, 'user', 0, 0, stt_blocks])
    bot.send_message(user_id, stt_text, reply_to_message_id=message.id, reply_markup=menu_keyboard(["/start", "/stt", "/tts", "/help"]))


@bot.message_handler(commands=['tts'])
def tts_handler(message):
    user_id = message.from_user.id
    bot.send_message(user_id, 'Отправь следующим сообщением текст, чтобы я его озвучил!')
    bot.register_next_step_handler(message, tts)


def tts(message):
    user_id = message.from_user.id
    text = message.text
    # Проверка, что сообщение действительно текстовое
    if message.content_type != 'text':
        bot.send_message(user_id, 'Отправь текстовое сообщение')
        return
    bot.send_message(user_id, 'Ждём твета...')
    tts_symbols, error_message = is_tts_symbol_limit(user_id, text)
    # Запись ответа GPT в БД
    add_message(user_id=user_id, full_message=[0, 'assistant', 0, tts_symbols, 0])
    if error_message:
        bot.send_message(user_id, error_message)
        return
    # Преобразование ответа в аудио и отправка
    status_tts, voice_response = text_to_speech(text)
    if status_tts:
        bot.send_voice(user_id, voice_response, reply_to_message_id=message.id)
    else:
        bot.send_message(user_id, text, reply_to_message_id=message.id, reply_markup=menu_keyboard(["/start", "/stt", "/tts", "/help"]))


@bot.message_handler(content_types=['voice'])
def handle_voice(message: telebot.types.Message):
    try:
        user_id = message.from_user.id
        status_check_users, error_message = check_number_of_users(user_id)
        if not status_check_users:
            bot.send_message(user_id, error_message)
            return
        stt_blocks, error_message = is_stt_block_limit(message, message.voice.duration)
        if error_message:
            bot.send_message(user_id, error_message)
            return
        file_id = message.voice.file_id
        file_info = bot.get_file(file_id)
        file = bot.download_file(file_info.file_path)
        status_stt, stt_text = speech_to_text(file)
        if not status_stt:
            bot.send_message(user_id, stt_text)
            return
        add_message(user_id=user_id, full_message=[stt_text, 'user', 0, 0, stt_blocks])
        last_messages, total_spent_tokens = select_n_last_messages(user_id, COUNT_LAST_MSG)
        total_gpt_tokens, error_message = is_gpt_token_limit(last_messages, total_spent_tokens)
        if error_message:
            bot.send_message(user_id, error_message)
            return
        status_gpt, answer_gpt, tokens_in_answer = ask_gpt(last_messages)
        if not status_gpt:
            bot.send_message(user_id, answer_gpt)
            return
        total_gpt_tokens += tokens_in_answer
        tts_symbols, error_message = is_tts_symbol_limit(message, answer_gpt)
        add_message(user_id=user_id, full_message=[answer_gpt, 'assistant', total_gpt_tokens, tts_symbols, 0])
        if error_message:
            bot.send_message(user_id, error_message)
            return
        status_tts, voice_response = text_to_speech(answer_gpt)
        if status_tts:
            bot.send_voice(user_id, voice_response, reply_to_message_id=message.id)
        else:
            bot.send_message(user_id, answer_gpt, reply_to_message_id=message.id)
    except Exception as e:
        logging.error(e)
        bot.send_message(user_id, "Не получилось ответить. Попробуйте записать другое сообщение")


@bot.message_handler(content_types=['text'])
def handle_text(message):
    try:
        user_id = message.from_user.id
        status_check_users, error_message = check_number_of_users(user_id)
        if not status_check_users:
            bot.send_message(user_id, error_message)
            return
        full_user_message = [message.text, 'user', 0, 0, 0]
        add_message(user_id=user_id, full_message=full_user_message)
        last_messages, total_spent_tokens = select_n_last_messages(user_id, COUNT_LAST_MSG)
        total_gpt_tokens, error_message = is_gpt_token_limit(last_messages, total_spent_tokens)
        if error_message:
            bot.send_message(user_id, error_message)
            return
        status_gpt, answer_gpt, tokens_in_answer = ask_gpt(last_messages)
        if not status_gpt:
            bot.send_message(user_id, answer_gpt)
            return
        total_gpt_tokens += tokens_in_answer
        full_gpt_message = [answer_gpt, 'assistant', total_gpt_tokens, 0, 0]
        add_message(user_id=user_id, full_message=full_gpt_message)
        bot.send_message(user_id, answer_gpt, reply_to_message_id=message.id)
    except Exception as e:
        logging.error(e)
        bot.send_message(user_id, "Не получилось ответить. Попробуйте написать другое сообщение")


@bot.message_handler(func=lambda _: True)
def handler(message):
    bot.send_message(message.from_user.id, "Отправь мне голосовое или текстовое сообщение, и я тебе отвечу")


create_database()
bot.polling()