"""
Утилита управления пользователями.
Запуск: python manage_users.py add <login> <password> <"Полное имя"> <role>
Пример: python manage_users.py add operator2 pass456 "Смирнов А.В." user
"""

import sys
import yaml
import bcrypt
import os

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yml")

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

def add_user(login, password, name, role="user"):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
    cfg = load_config()
    if login in cfg["credentials"]["usernames"]:
        print(f"❌ Пользователь '{login}' уже существует.")
        return False
    cfg["credentials"]["usernames"][login] = {
        "name": name,
        "password": hashed,
        "role": role,
    }
    save_config(cfg)
    print(f"✅ Пользователь '{login}' (роль: {role}) добавлен.")
    return True

def remove_user(login):
    cfg = load_config()
    if login not in cfg["credentials"]["usernames"]:
        print(f"❌ Пользователь '{login}' не найден.")
        return False
    del cfg["credentials"]["usernames"][login]
    save_config(cfg)
    print(f"✅ Пользователь '{login}' удалён.")
    return True

def list_users():
    cfg = load_config()
    users = cfg["credentials"]["usernames"]
    print(f"{'Логин':<20} {'Имя':<30} {'Роль'}")
    print("-" * 60)
    for u, v in users.items():
        print(f"{u:<20} {v.get('name',''):<30} {v.get('role','user')}")

def change_password(login, new_password):
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(12)).decode()
    cfg = load_config()
    if login not in cfg["credentials"]["usernames"]:
        print(f"❌ Пользователь '{login}' не найден.")
        return False
    cfg["credentials"]["usernames"][login]["password"] = hashed
    save_config(cfg)
    print(f"✅ Пароль для '{login}' изменён.")
    return True

def gen_hash(password):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
    print(f"Hash for '{password}':\n{hashed}")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Использование:")
        print("  python manage_users.py add <login> <password> <name> [role]")
        print("  python manage_users.py remove <login>")
        print("  python manage_users.py list")
        print("  python manage_users.py passwd <login> <new_password>")
        print("  python manage_users.py hash <password>")
        sys.exit(0)

    cmd = args[0]
    if cmd == "add":
        if len(args) < 4:
            print("❌ Нужно: add <login> <password> <name> [role]")
            sys.exit(1)
        role = args[4] if len(args) > 4 else "user"
        add_user(args[1], args[2], args[3], role)
    elif cmd == "remove":
        remove_user(args[1])
    elif cmd == "list":
        list_users()
    elif cmd == "passwd":
        change_password(args[1], args[2])
    elif cmd == "hash":
        gen_hash(args[1])
    else:
        print(f"❌ Неизвестная команда: {cmd}")
