"""
Скрипт для генерации config.yml с реальными bcrypt хешами.
Запускается при сборке Docker-образа.
"""
import bcrypt
import yaml
import os

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yml")

def gen_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")

config = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "Администратор",
                "password": gen_hash("admin123"),
                "role": "admin",
            },
            "user1": {
                "name": "Оператор Иванов А.А.",
                "password": gen_hash("user123"),
                "role": "user",
            },
        }
    },
    "cookie": {
        "expiry_days": 7,
        "key": "lathe_control_secret_key_2024_xK9mP",
        "name": "lathe_auth_cookie",
    },
    "preauthorized": {
        "emails": []
    }
}

with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

print(f"✅ {CONFIG_PATH} сгенерирован")
print(f"   admin  / admin123")
print(f"   user1  / user123")
