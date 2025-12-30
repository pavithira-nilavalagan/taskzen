from flask import Flask, render_template, request, redirect, session,jsonify
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from bson import ObjectId
from werkzeug.utils import secure_filename
import os
import requests

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
profiles = db.profiles
chat_history = db.chat_history
tasks_collection = db.tasks_collection


UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------- HOME ----------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        users.insert_one({
            "name": request.form["name"],
            "email": request.form["email"],
            "password": generate_password_hash(request.form["password"]),
            "profile": {},
            "created": datetime.now()
        })
        return redirect("/login")
    return render_template("register.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = users.find_one({"email": request.form["email"]})

        if user and check_password_hash(user["password"], request.form["password"]):
            session["user_id"] = str(user["_id"])   # ✅ ADD THIS
            session["user"] = user["email"]

            return redirect("/dashboard")

    return render_template("login.html")


# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]

    # Fetch only tasks for the logged-in user
    all_tasks = list(tasks_collection.find({"user": user_email}))
    
    total_tasks = len(all_tasks)
    completed_tasks = len([t for t in all_tasks if t['status'] == 'Completed'])
    pending_tasks = len([t for t in all_tasks if t['status'] == 'Pending'])
    high_priority_tasks = len([t for t in all_tasks if t['priority'] == 'High'])
    
    completion_percentage = int((completed_tasks / total_tasks) * 100) if total_tasks else 0

    # Fetch 5 most recent tasks
    recent_tasks = list(tasks_collection.find({"user": user_email}).sort("created", -1).limit(5))

    return render_template("dashboard.html",
                           total_tasks=total_tasks,
                           completed_tasks=completed_tasks,
                           pending_tasks=pending_tasks,
                           high_priority_tasks=high_priority_tasks,
                           completion_percentage=completion_percentage,
                           recent_tasks=recent_tasks)



# ---------------- PROFILE ----------------
@app.route("/profile", methods=["GET", "POST"])
def profile():
    user_email = session.get("user")
    profile = users.find_one({"email": user_email})  # Replace with your Mongo query

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

        # Handle file upload
        file = request.files.get("image")
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            update_data["image_url"] = "/" + filepath.replace("\\", "/")

        # Update database
        users.update_one({"email": user_email}, {"$set": update_data}, upsert=True)

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
            "created": datetime.now().strftime("%Y-%m-%d %H:%M")
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

# Gemini API key from environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def call_gemini_api(message):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": message}
                    ]
                }
            ]
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            data = response.json()
            # The text is usually nested inside content.parts
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print("Gemini API Response:", response.text)
            return f"⚠️ Gemini API Error: {response.status_code} - {response.text}"

    except Exception as e:
        return f"⚠️ Exception calling Gemini API: {e}"



# ---------------- ZENBOT ROUTE ----------------
@app.route("/zenbot", methods=["GET", "POST"])
def zenbot():
    if "user" not in session:
        return redirect("/login")

    user_email = session["user"]
    user = users.find_one({"email": user_email})

    if request.method == "POST":
        try:
            data = request.json
            message = data.get("message")
            if not message:
                return jsonify({"error": "Message required"}), 400

            # Get AI reply
            reply = call_gemini_api(message)

            # Save chat history
            chat_history.insert_one({
                "user": user_email,
                "message": message,
                "reply": reply,
                "timestamp": datetime.now()
            })

            # Auto-create task if message starts with "Add task:"
            if message.lower().startswith("add task:"):
                try:
                    _, task_data = message.split("add task:", 1)
                    title, description, priority, due_date = [x.strip() for x in task_data.split(";")]
                    tasks.insert_one({
                        "user": user_email,
                        "title": title,
                        "description": description,
                        "priority": priority.capitalize(),
                        "due_date": due_date,
                        "status": "Pending",
                        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
                    })
                    reply += f"\n✅ Task '{title}' created successfully!"
                except Exception as e:
                    reply += f"\n⚠️ Could not create task: {e}"

            return jsonify({"reply": reply})

        except Exception as e:
            return jsonify({"error": f"Server error: {e}"}), 500

    # ---------------- GET REQUEST ----------------
    history = list(chat_history.find({"user": user_email}).sort("timestamp", -1).limit(20))
    history.reverse()  # oldest first
    return render_template("zenbot.html", history=history, user=user)

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0",debug=True)
