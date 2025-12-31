from flask import Flask, render_template, request, redirect, session,jsonify
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from bson import ObjectId
from werkzeug.utils import secure_filename
import os
import requests
import json
import re

from dotenv import load_dotenv

load_dotenv()  # loads variables from .env into environment

app = Flask(__name__)
app.secret_key = "taskzen_secret"



# MongoDB Atlas
MONGO_URI = os.getenv("MONGO_URI_ATLAS")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI_ATLAS not found")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, authSource="admin")

# Test connection
try:
    client.admin.command("ping")
    print("MongoDB Atlas connected ✅")
except Exception as e:
    print("MongoDB connection failed ❌")
    print(e)

# 🔥 IMPORTANT: Explicit DB selection
db = client["taskzen"]

# Collections
users = db.users
tasks = db.tasks
chat_history = db.chat_history



UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# 🔥 THIS LINE FIXES EVERYTHING
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------- HOME ----------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            email = request.form["email"]

            # Check duplicate
            if users.find_one({"email": email}):
                return render_template("register.html", error="Email already exists")

            users.insert_one({
                "name": request.form["name"],
                "email": email,
                "password": generate_password_hash(request.form["password"]),
                "settings": {},
                "created": datetime.utcnow()
            })

            print("✅ User inserted into MongoDB Atlas")

            return redirect("/login")

        except Exception as e:
            print("❌ Registration error:", e)
            return render_template("register.html", error="Registration failed")

    return render_template("register.html")


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            email = request.form.get("email")
            password = request.form.get("password")

            if not email or not password:
                return render_template(
                    "login.html",
                    error="Email and password are required"
                )

            # 🔍 Find user in MongoDB Atlas
            user = users.find_one({"email": email})

            if not user:
                return render_template(
                    "login.html",
                    error="User does not exist"
                )

            # 🔐 Check password hash
            if not check_password_hash(user["password"], password):
                return render_template(
                    "login.html",
                    error="Invalid password"
                )

            # ✅ Login success
            session.clear()
            session["user_id"] = str(user["_id"])
            session["user"] = user["email"]

            print("✅ User logged in:", email)

            return redirect("/dashboard")

        except Exception as e:
            print("❌ Login error:", e)
            return render_template(
                "login.html",
                error="Login failed, try again"
            )

    return render_template("login.html")



# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]

    # ✅ FIXED: use tasks collection
    all_tasks = list(tasks.find({"user": user_email}))

    total_tasks = len(all_tasks)
    completed_tasks = len([t for t in all_tasks if t["status"] == "Completed"])
    pending_tasks = len([t for t in all_tasks if t["status"] == "Pending"])
    high_priority_tasks = len([t for t in all_tasks if t["priority"] == "High"])

    completion_percentage = int((completed_tasks / total_tasks) * 100) if total_tasks else 0

    # ✅ FIXED: recent tasks
    recent_tasks = list(
        tasks.find({"user": user_email})
        .sort("created", -1)
        .limit(5)
    )

    return render_template(
        "dashboard.html",
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        high_priority_tasks=high_priority_tasks,
        completion_percentage=completion_percentage,
        recent_tasks=recent_tasks
    )




# ---------------- PROFILE ----------------
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]
    profile = users.find_one({"email": user_email})

    if request.method == "POST":
        update_data = {
            "phone": request.form.get("phone"),
            "dob": request.form.get("dob"),
            "gender": request.form.get("gender"),
            "city": request.form.get("city"),
            "state": request.form.get("state"),
            "country": request.form.get("country"),
            "address": request.form.get("address"),
            "bio": request.form.get("bio"),
        }

        # Only update image if a new file is uploaded
        file = request.files.get("image")
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = f"{ObjectId()}_{filename}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            update_data["image_url"] = f"/static/uploads/{filename}"
        else:
            # Keep existing image if no new file
            if "image_url" in profile:
                update_data["image_url"] = profile["image_url"]

        users.update_one(
            {"email": user_email},
            {"$set": update_data}
        )

        return redirect("/profile")

    return render_template("profile.html", profile=profile)





# ---------------- ADD TASK ----------------
@app.route("/add-task", methods=["GET","POST"])
def add_task():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":
        tasks.insert_one({
            "user": session["user"],
            "title": request.form["title"],
            "description": request.form["description"],
            "priority": request.form["priority"],
            "due_date": request.form["due_date"],
            "status": "Pending",
            "created": datetime.utcnow()

        })
        return redirect("/tasks")

    return render_template("add_task.html")


# ---------------- ALL TASKS ----------------

@app.route("/tasks")
def all_tasks():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]

    # 1️⃣ Fetch logged-in user info
    user = users.find_one({"email": user_email})  # <-- make sure your users collection exists

    # 2️⃣ Build query for tasks
    query = {"user": user_email}

    search = request.args.get("search")
    priority = request.args.get("priority")
    status = request.args.get("status")

    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}}
        ]

    if priority and priority != "All":
        query["priority"] = priority

    if status and status != "All":
        query["status"] = status

    # 3️⃣ Fetch tasks
    data = tasks.find(query).sort("created", -1)

    # 4️⃣ Pass user info to template
    return render_template("tasks.html", tasks=data, user=user)

# ---------------- UPDATE TASK ----------------
@app.route("/update-task/<id>", methods=["POST"])
def update_task(id):
    tasks.update_one(
        {"_id": ObjectId(id)},
        {"$set":{
            "title": request.form["title"],
            "description": request.form["description"],
            "priority": request.form["priority"],
            "status": request.form["status"]
        }}
    )
    return redirect("/tasks")

# ---------------- DELETE TASK ----------------
@app.route("/delete-task/<id>")
def delete_task(id):
    tasks.delete_one({"_id": ObjectId(id)})
    return redirect("/tasks")

# ---------------- FILTER PAGES ----------------
@app.route("/completed")
def completed():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]

    # 1️⃣ Fetch logged-in user info
    user = users.find_one({"email": user_email})  # <-- make sure your users collection exists
    
    data = tasks.find({"user":session["user"],"status":"Completed"})
    return render_template("completed.html", tasks=data, user=user)

@app.route("/pending")
def pending():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]

    # 1️⃣ Fetch logged-in user info
    user = users.find_one({"email": user_email})  # <-- make sure your users collection exists
    data = tasks.find({"user":session["user"],"status":"Pending"})
    return render_template("pending.html", tasks=data, user=user)

@app.route("/priority")
def priority():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]

    # 1️⃣ Fetch logged-in user info
    user = users.find_one({"email": user_email})  # <-- make sure your users collection exists
    data = tasks.find({"user":session["user"],"priority":"High"})
    return render_template("priority.html", tasks=data, user=user)


# ---------------- SETTINGS ----------------
# ---------------- SETTINGS ----------------
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]
    user = users.find_one({"email": user_email})

    # ✅ Ensure settings exist (fixes UndefinedError)
    if "settings" not in user:
        users.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "settings": {
                    "theme": "light",
                    "email_notifications": False,
                    "task_reminders": False,
                    "default_priority": "Medium",
                    "timezone": "Asia/Kolkata"
                }
            }}
        )
        user = users.find_one({"_id": user["_id"]})

    if request.method == "POST":

        name = request.form.get("name")
        new_email = request.form.get("email")

        # ✅ Prevent duplicate email
        if new_email != user_email:
            if users.find_one({"email": new_email}):
                return render_template(
                    "settings.html",
                    user=user,
                    error="Email already exists"
                )

        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        update_data = {
            "name": name,
            "email": new_email,
            "settings.theme": request.form.get("theme"),
            "settings.email_notifications": True if request.form.get("email_notifications") else False,
            "settings.task_reminders": True if request.form.get("task_reminders") else False,
            "settings.default_priority": request.form.get("default_priority"),
            "settings.timezone": request.form.get("timezone")
        }

        # 🔐 Change password (optional)
        if current_password and new_password:
            if check_password_hash(user["password"], current_password):
                if new_password == confirm_password:
                    update_data["password"] = generate_password_hash(new_password)
                else:
                    return render_template(
                        "settings.html",
                        user=user,
                        error="New passwords do not match"
                    )
            else:
                return render_template(
                    "settings.html",
                    user=user,
                    error="Current password is incorrect"
                )

        users.update_one(
            {"_id": user["_id"]},
            {"$set": update_data}
        )

        session["user"] = new_email

        return redirect("/settings")

    return render_template("settings.html", user=user)




@app.route("/calendar")
def calendar():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]



    # 1️⃣ Fetch logged-in user info
    user = users.find_one({"email": user_email})  # <-- make sure your users collection exists
    
    

    task_list = list(tasks.find({"user": user_email}))

    events = []
    for t in task_list:
        # Priority colors
        color = "#22c55e"  # Low = green
        if t["priority"] == "High":
            color = "#ef4444"  # red
        elif t["priority"] == "Medium":
            color = "#eab308"  # yellow

        events.append({
            "id": str(t["_id"]),
            "title": t["title"],
            "start": t["due_date"],  # YYYY-MM-DD
            "backgroundColor": color,
            "borderColor": color
        })

    return render_template("calendar.html", events=events, user=user)

@app.route("/complete-task/<id>")
def complete_task(id):
    tasks.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Completed"}}
    )
    return ("", 204)


# ---------------- ZENBOT ----------------
@app.route("/zenbot", methods=["GET", "POST"])
def zenbot():
    if "user" not in session:
        return redirect("/login")
    user_email = session["user"]
    user = users.find_one({"email": user_email})

    if request.method == "POST":
        try:
            data = request.get_json()
            message = data.get("message", "").strip()
            if not message:
                return jsonify({"reply": "⚠️ Message cannot be empty"})

            # ---------------- JS-style Intent Detection ----------------
            message_lower = message.lower()
            intent = "unknown"
            task_title = None

            if re.search(r"\badd\b|\bcreate\b", message_lower):
                intent = "add_task"
                task_title = re.sub(r"(add|create|to-do|todo|list)", "", message_lower).strip()
            elif re.search(r"\blist\b|\bshow\b", message_lower):
                intent = "list_tasks"
            elif re.search(r"\bcomplete\b|\bdone\b", message_lower):
                intent = "complete_task"
                task_title = re.sub(r"(complete|finished|done)", "", message_lower).strip()
            elif re.search(r"\bremove\b|\bdelete\b", message_lower):
                intent = "delete_task"
                task_title = re.sub(r"(remove|delete)", "", message_lower).strip()

            reply = "🤖 I can help with tasks. Try adding or listing tasks."

            # ---------------- Execute Intent ----------------
            if intent == "add_task" and task_title:
                tasks.insert_one({
                    "user": user_email,
                    "title": task_title.title(),
                    "description": "",
                    "priority": "Medium",
                    "due_date": "",
                    "status": "Pending",
                    "created": datetime.utcnow()
                })
                reply = f"✅ Task '{task_title.title()}' added!"

            elif intent == "list_tasks":
                task_list = list(tasks.find({"user": user_email}))
                if task_list:
                    reply = "📝 Your tasks:\n" + "\n".join(
                        f"- {t['title']} ({t['status']})" for t in task_list
                    )
                else:
                    reply = "📭 No tasks found."

            elif intent == "complete_task" and task_title:
                result = tasks.update_one(
                    {"user": user_email, "title": {"$regex": f"^{re.escape(task_title)}$", "$options":"i"}},
                    {"$set": {"status": "Completed"}}
                )
                reply = "✅ Task completed!" if result.modified_count else "⚠️ Task not found."

            elif intent == "delete_task" and task_title:
                result = tasks.delete_one(
                    {"user": user_email, "title": {"$regex": f"^{re.escape(task_title)}$", "$options":"i"}}
                )
                reply = "🗑️ Task deleted!" if result.deleted_count else "⚠️ Task not found."

            # ---------------- Save Chat History ----------------
            chat_history.insert_one({
                "user": user_email,
                "message": message,
                "reply": reply,
                "timestamp": datetime.utcnow()
            })

            return jsonify({"reply": reply})

        except Exception as e:
            print("ZenBot error:", e)
            return jsonify({"reply": f"⚠️ Server error: {e}"}), 500

    # ---------------- GET request: render page ----------------
    history = list(chat_history.find({"user": user_email}).sort("timestamp", 1))
    return render_template("zenbot.html", history=history, user=user)

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0",debug=True)











