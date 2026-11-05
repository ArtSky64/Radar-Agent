import pytest
import rag_agent


def test_context_retention_and_meta_query():
    # 1. Первый вопрос в совершенно новом диалоге: "А что мы обсуждали ранее?"
    res_initial = rag_agent.process_dialogue(
        history=[{"role": "user", "content": "А что мы обсуждали ранее?"}],
    )
    assert res_initial["role"] == "assistant"
    assert "ещё ничего не обсуждали" in res_initial["content"] or "новый диалог" in res_initial["content"]

    # 2. Пользователь задает содержательный вопрос
    user_q = "Найди датасеты для выявления кибератак и безопасности"
    res_topic = rag_agent.process_dialogue(
        history=[{"role": "user", "content": user_q}],
        max_sources=3,
    )
    assert res_topic["role"] == "assistant"
    topic_reply = res_topic["content"]
    assert len(topic_reply) > 20

    # 3. Пользователь спрашивает в рамках того же диалога: "А что мы делали ранее?"
    history_with_context = [
        {"role": "user", "content": user_q},
        {"role": "assistant", "content": topic_reply},
        {"role": "user", "content": "А что мы делали ранее?"},
    ]
    res_context = rag_agent.process_dialogue(
        history=history_with_context,
    )
    assert res_context["role"] == "assistant"
    # Должен вспомнить предыдущий вопрос/тему про кибератаки
    assert "кибератак" in res_context["content"].lower() or "безопасности" in res_context["content"].lower()

    # 4. Пользователь нажимает "Новый чат" (открывается независимая вкладка) и снова спрашивает: "что мы обсуждали ранее?"
    res_cleared = rag_agent.process_dialogue(
        history=[{"role": "user", "content": "Что мы обсуждали ранее?"}],
    )
    assert "ещё ничего не обсуждали" in res_cleared["content"] or "новый диалог" in res_cleared["content"]


def test_independent_sessions_isolation():
    # Сессия 1: Обсуждали модели распознавания речи
    session1_history = [
        {"role": "user", "content": "Посоветуй модели для распознавания речи Whisper"},
        {"role": "assistant", "content": "Рекомендую использовать [OpenAI Whisper-large-v3](https://huggingface.co/openai/whisper-large-v3) и [Whisper-turbo](https://huggingface.co/openai/whisper-turbo)."},
    ]

    # Запрос истории в Сессии 1
    session1_meta = rag_agent.process_dialogue(
        history=session1_history + [{"role": "user", "content": "Напомни, что мы делали"}],
    )
    assert "распознавания речи" in session1_meta["content"].lower() or "whisper" in session1_meta["content"].lower()

    # Сессия 2: Полностью новая вкладка, спрашивает историю
    session2_meta = rag_agent.process_dialogue(
        history=[{"role": "user", "content": "Что мы делали ранее?"}],
    )
    # Сессия 2 не должна знать ничего про Whisper из Сессии 1
    assert "whisper" not in session2_meta["content"].lower()
    assert "ещё ничего не обсуждали" in session2_meta["content"].lower() or "новый диалог" in session2_meta["content"].lower()


def test_multiturn_refinement_and_concise_summary():
    # Симулируем последовательный диалог:
    # 1. Пользователь: "машинное обучение"
    # 2. Пользователь: "репо"
    # 3. Пользователь: "нлп"
    # 4. Пользователь: "модели" -> ассистент должен искать модели для NLP / ML, а не переспрашивать "тема обширна"!
    dialogue = [
        {"role": "user", "content": "машинное обучение"},
        {"role": "assistant", "content": "Тема машинного обучения обширна. Уточните направление: NLP, компьютерное зрение или табличные данные?"},
        {"role": "user", "content": "репо"},
        {"role": "assistant", "content": "Понял, ищем репозитории по машинному обучению."},
        {"role": "user", "content": "нлп"},
        {"role": "assistant", "content": "Вот репозитории по обработке естественного языка (NLP): Hugging Face Transformers, Spacy."},
        {"role": "user", "content": "модели"},
    ]

    res_models = rag_agent.process_dialogue(history=dialogue, max_sources=3)
    assert res_models["role"] == "assistant"
    # Не должно быть глупого уточнения "тема модели обширна! вас интересуют модели или датасеты?"
    assert "вас интересуют готовые модели или сырые датасеты" not in res_models["content"].lower()
    # Ответ не должен начинаться с "Привет!" (нет повторного приветствия)
    assert not res_models["content"].strip().lower().startswith("привет")

    # 5. Пользователь спрашивает: "о чем говорили ранее"
    full_history = dialogue + [
        {"role": "assistant", "content": res_models["content"]},
        {"role": "user", "content": "о чем говорили ранее"},
    ]
    res_summary = rag_agent.process_dialogue(history=full_history)
    assert res_summary["role"] == "assistant"
    summary_text = res_summary["content"]

    # Проверяем, что это связная выжимка, а не механический список "Запрос пользователя: ... ↳ Что было сделано: ..."
    assert "Запрос пользователя:" not in summary_text
    assert "Что было сделано:" not in summary_text
    assert "выжимка" in summary_text.lower()
    # Темы должны быть упомянуты
    assert "машинном" in summary_text.lower() or "nlp" in summary_text.lower() or "обучени" in summary_text.lower()
