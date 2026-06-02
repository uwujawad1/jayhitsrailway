import sys
import json
import os

SITES_FILE = os.path.join(os.path.dirname(__file__), "user_sites.json")

def load_sites():
    try:
        if os.path.exists(SITES_FILE):
            with open(SITES_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_sites(data):
    with open(SITES_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_user_sites(user_id):
    data = load_sites()
    return data.get(str(user_id), [])

def add_user_sites(user_id, urls):
    data = load_sites()
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    added = []
    for url in urls:
        clean = url.strip().replace("https://", "").replace("http://", "").rstrip("/")
        if clean and clean not in data[uid]:
            data[uid].append(clean)
            added.append(clean)
    save_sites(data)
    return added

def remove_user_site(user_id, url):
    data = load_sites()
    uid = str(user_id)
    if uid not in data:
        return False
    clean = url.strip().replace("https://", "").replace("http://", "").rstrip("/")
    if clean in data[uid]:
        data[uid].remove(clean)
        if not data[uid]:
            del data[uid]
        save_sites(data)
        return True
    return False

def clear_user_sites(user_id):
    data = load_sites()
    uid = str(user_id)
    if uid in data:
        count = len(data[uid])
        del data[uid]
        save_sites(data)
        return count
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: web_shopify_sites.py <action> <user_id> [args...]"}))
        sys.exit(1)

    action = sys.argv[1]
    user_id = sys.argv[2]

    if action == "list":
        sites = get_user_sites(user_id)
        print(json.dumps({"sites": sites, "count": len(sites)}))
    elif action == "add":
        urls = sys.argv[3:]
        added = add_user_sites(user_id, urls)
        print(json.dumps({"added": added, "count": len(added)}))
    elif action == "remove":
        url = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = remove_user_site(user_id, url)
        print(json.dumps({"removed": ok}))
    elif action == "clear":
        count = clear_user_sites(user_id)
        print(json.dumps({"cleared": count}))
    else:
        print(json.dumps({"error": f"Unknown action: {action}"}))
