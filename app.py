import os
import base64
import json
import uuid
import datetime
import sqlite3
import requests
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# --- CONFIGURATION & DATABASE SETUP ---
# Note: In the preview environment, the Gemini API key is managed automatically.
API_KEY = ""
MODEL_NAME = "gemini-2.5-flash-preview-09-2025"

app = FastAPI(title="CivicEye AI")

def init_db():
    """Initializes the SQLite database for storing reports."""
    conn = sqlite3.connect("civic_issues.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            category TEXT,
            severity TEXT,
            description TEXT,
            location TEXT,
            status TEXT,
            timestamp DATETIME,
            image_path TEXT,
            urgency_score INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- HELPER FUNCTIONS ---

def get_ai_analysis(image_base64: str, user_description: str):
    """
    Sends the image to Gemini 2.5 Flash to identify the civic issue,
    severity, and urgency score.
    """
    system_prompt = """
    You are an expert Civic Infrastructure Analyst. Analyze the provided image of a city issue.
    Identify:
    1. Category (Pothole, Garbage Overflow, Broken Streetlight, Water Leakage, Unsafe Area, Other).
    2. Severity (Low, Medium, High, Critical).
    3. Urgency Score (1-10, where 10 is immediate danger to life).
    4. Brief technical summary.
    
    Return ONLY a JSON object:
    {"category": "...", "severity": "...", "urgency_score": 8, "summary": "..."}
    """
    
    user_query = f"User reported: {user_description if user_description else 'No description provided.'}"
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"
    
    payload = {
        "contents": [{
            "parts": [
                {"text": user_query},
                {"inlineData": {"mimeType": "image/jpeg", "data": image_base64}}
            ]
        }],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    # Exponential backoff retry logic
    for delay in [1, 2, 4, 8, 16]:
        try:
            response = requests.post(url, json=payload)
            if response.status_status == 200:
                result = response.json()
                text_content = result['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text_content)
        except Exception:
            pass
    return {"category": "Unidentified", "severity": "Medium", "urgency_score": 5, "summary": "AI analysis failed."}

# --- API ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def index():
    """Returns the main UI for reporting and dashboard."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CivicEye AI | Smart City Reporting</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    </head>
    <body class="bg-slate-50 text-slate-900 font-sans">
        <nav class="bg-blue-600 text-white p-4 shadow-lg">
            <div class="container mx-auto flex justify-between items-center">
                <h1 class="text-2xl font-bold flex items-center gap-2">
                    <i class="fas fa-city"></i> CivicEye AI
                </h1>
                <div class="space-x-4">
                    <button onclick="showSection('report')" class="hover:underline">Report Issue</button>
                    <button onclick="showSection('dashboard')" class="hover:underline">Authority Dashboard</button>
                </div>
            </div>
        </nav>

        <main class="container mx-auto mt-8 p-4">
            <!-- REPORTING SECTION -->
            <section id="report-section" class="max-w-2xl mx-auto bg-white p-8 rounded-xl shadow-md">
                <h2 class="text-2xl font-semibold mb-6">Report a Civic Issue</h2>
                <form id="report-form" class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium mb-1">Upload Photo</label>
                        <input type="file" id="imageInput" accept="image/*" class="w-full border p-2 rounded" required>
                    </div>
                    <div>
                        <label class="block text-sm font-medium mb-1">Location Tag</label>
                        <input type="text" id="locationInput" placeholder="e.g., 5th Avenue, Near Central Park" class="w-full border p-2 rounded" required>
                    </div>
                    <div>
                        <label class="block text-sm font-medium mb-1">Description (Optional)</label>
                        <textarea id="descInput" class="w-full border p-2 rounded h-24" placeholder="Describe the problem..."></textarea>
                    </div>
                    <button type="submit" id="submitBtn" class="w-full bg-blue-600 text-white py-3 rounded-lg font-bold hover:bg-blue-700 transition">
                        Submit Report
                    </button>
                </form>
                <div id="loading" class="hidden mt-4 text-center text-blue-600 font-semibold">
                    <i class="fas fa-spinner fa-spin mr-2"></i> Analyzing issue with AI...
                </div>
            </section>

            <!-- DASHBOARD SECTION -->
            <section id="dashboard-section" class="hidden">
                <div class="flex justify-between items-center mb-6">
                    <h2 class="text-2xl font-semibold">Live Issues Map & Priority List</h2>
                    <button onclick="loadReports()" class="bg-slate-200 px-4 py-2 rounded hover:bg-slate-300">
                        <i class="fas fa-sync"></i> Refresh
                    </button>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" id="reports-grid">
                    <!-- Cards injected here -->
                </div>
            </section>
        </main>

        <script>
            function showSection(section) {
                document.getElementById('report-section').classList.toggle('hidden', section !== 'report');
                document.getElementById('dashboard-section').classList.toggle('hidden', section !== 'dashboard');
                if(section === 'dashboard') loadReports();
            }

            document.getElementById('report-form').onsubmit = async (e) => {
                e.preventDefault();
                const btn = document.getElementById('submitBtn');
                const loading = document.getElementById('loading');
                
                btn.disabled = true;
                loading.classList.remove('hidden');

                const file = document.getElementById('imageInput').files[0];
                const location = document.getElementById('locationInput').value;
                const desc = document.getElementById('descInput').value;

                const formData = new FormData();
                formData.append('image', file);
                formData.append('location', location);
                formData.append('description', desc);

                try {
                    const res = await fetch('/submit-report', { method: 'POST', body: formData });
                    const data = await res.json();
                    alert(`Report Submitted Successfully!\\nCategory: ${data.category}\\nSeverity: ${data.severity}`);
                    document.getElementById('report-form').reset();
                    showSection('dashboard');
                } catch (err) {
                    alert("Error submitting report.");
                } finally {
                    btn.disabled = false;
                    loading.classList.add('hidden');
                }
            };

            async function loadReports() {
                const grid = document.getElementById('reports-grid');
                grid.innerHTML = '<p class="col-span-full text-center py-10">Loading active reports...</p>';
                
                try {
                    const res = await fetch('/get-reports');
                    const data = await res.json();
                    grid.innerHTML = '';
                    
                    data.forEach(report => {
                        const severityColor = {
                            'Critical': 'bg-red-100 text-red-800 border-red-200',
                            'High': 'bg-orange-100 text-orange-800 border-orange-200',
                            'Medium': 'bg-yellow-100 text-yellow-800 border-yellow-200',
                            'Low': 'bg-green-100 text-green-800 border-green-200'
                        }[report.severity] || 'bg-slate-100';

                        const card = `
                            <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden flex flex-col">
                                <div class="p-4 border-b bg-slate-50 flex justify-between items-center">
                                    <span class="text-xs font-bold uppercase tracking-wider text-slate-500">${report.timestamp}</span>
                                    <span class="px-2 py-1 rounded text-xs font-bold border ${severityColor}">${report.severity}</span>
                                </div>
                                <div class="p-5 flex-grow">
                                    <h3 class="font-bold text-lg mb-1">${report.category}</h3>
                                    <p class="text-sm text-slate-600 mb-3"><i class="fas fa-map-marker-alt mr-1"></i> ${report.location}</p>
                                    <p class="text-slate-700 text-sm italic">"${report.description}"</p>
                                </div>
                                <div class="p-4 bg-slate-50 border-t flex justify-between items-center">
                                    <div class="flex items-center gap-2">
                                        <div class="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold text-xs">
                                            ${report.urgency_score}
                                        </div>
                                        <span class="text-xs text-slate-500 font-medium">Urgency Score</span>
                                    </div>
                                    <span class="text-xs px-2 py-1 bg-blue-600 text-white rounded cursor-pointer hover:bg-blue-700">Update Status</span>
                                </div>
                            </div>
                        `;
                        grid.innerHTML += card;
                    });
                } catch (err) {
                    grid.innerHTML = '<p class="col-span-full text-center text-red-500">Failed to load reports.</p>';
                }
            }
        </script>
    </body>
    </html>
    """

@app.post("/submit-report")
async def submit_report(
    image: UploadFile = File(...),
    location: str = Form(...),
    description: Optional[str] = Form(None)
):
    """Processes the image, gets AI analysis, and saves to database."""
    # Convert image to base64 for AI processing
    content = await image.read()
    image_base64 = base64.b64encode(content).decode('utf-8')
    
    # AI Analysis
    analysis = get_ai_analysis(image_base64, description)
    
    report_id = str(uuid.uuid4())
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Save to Database
    conn = sqlite3.connect("civic_issues.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reports (id, category, severity, description, location, status, timestamp, urgency_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        report_id, 
        analysis.get('category', 'Other'), 
        analysis.get('severity', 'Medium'),
        analysis.get('summary', description),
        location,
        "Pending",
        timestamp,
        analysis.get('urgency_score', 5)
    ))
    conn.commit()
    conn.close()
    
    return {**analysis, "id": report_id}

@app.get("/get-reports")
async def get_reports():
    """Fetches all reports sorted by urgency score and timestamp."""
    conn = sqlite3.connect("civic_issues.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Sort by urgency_score (desc) then timestamp (desc)
    cursor.execute('SELECT * FROM reports ORDER BY urgency_score DESC, timestamp DESC')
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)# Smart-Civic-Reporting-System
