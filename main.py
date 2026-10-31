import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Настройка страницы
st.set_page_config(
    page_title="Мой первый сайт",
    page_icon="🚀",
    layout="centered"
)

# Боковая панель
with st.sidebar:
    st.header("⚙️ Настройки")
    name = st.text_input("Как вас зовут?", "Гость")
    theme = st.selectbox("Тема", ["Светлая", "Тёмная"])
    st.write(f"Привет, **{name}**! 👋")

# Главный заголовок
st.title("🚀 Мой первый сайт на Streamlit")
st.write("Это простой пример интерактивного веб-приложения на Python.")

st.divider()

# --- Блок 1: Калькулятор ---
st.header("🧮 Калькулятор")

col1, col2 = st.columns(2)
with col1:
    num1 = st.number_input("Первое число", value=0.0, step=1.0)
with col2:
    num2 = st.number_input("Второе число", value=0.0, step=1.0)

operation = st.radio(
    "Операция",
    ["+", "-", "×", "÷"],
    horizontal=True
)

if st.button("Посчитать", type="primary"):
    try:
        if operation == "+":
            result = num1 + num2
        elif operation == "-":
            result = num1 - num2
        elif operation == "×":
            result = num1 * num2
        else:
            result = num1 / num2 if num2 != 0 else "Ошибка: деление на ноль"
        st.success(f"Результат: **{result}**")
    except Exception as e:
        st.error(f"Ошибка: {e}")

st.divider()

# --- Блок 2: Визуализация ---
st.header("📊 Визуализация данных")

rows = st.slider("Сколько точек показать?", 10, 200, 50)
data = pd.DataFrame({
    "x": np.arange(rows),
    "y": np.random.randn(rows).cumsum(),
})
st.line_chart(data.set_index("x"))

with st.expander("Показать данные в таблице"):
    st.dataframe(data, use_container_width=True)

st.divider()

# --- Блок 3: Форма обратной связи ---
st.header("✉️ Обратная связь")

with st.form("feedback_form"):
    email = st.text_input("Email")
    message = st.text_area("Сообщение")
    rating = st.slider("Оцените сайт", 1, 5, 5)
    submitted = st.form_submit_button("Отправить")

    if submitted:
        if email and message:
            st.success(f"Спасибо, {name}! Ваше сообщение получено. Оценка: {rating} ⭐")
            st.balloons()
        else:
            st.warning("Пожалуйста, заполните все поля.")

st.divider()
st.caption("© 2025 Мой первый сайт на Streamlit")
