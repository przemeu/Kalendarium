from flask import Flask, render_template, request, send_file, redirect, url_for
import sqlite3
import os
import pandas as pd
from io import BytesIO
import re
from collections import Counter

app = Flask(__name__)
app.config['SECRET_KEY'] = 'arka-kalendarium-production-key'

def get_db_connection():
    conn = sqlite3.connect('Kalendarium.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/results', methods=['GET', 'POST'])
def results():
    conn = get_db_connection()
    
    # Base query
    query = "SELECT * FROM Mecze WHERE 1=1"
    params = []
    
    # Apply filters from form
    if request.method == 'POST':
        if request.form.get('sezon'):
            query += " AND Sezon = ?"
            params.append(request.form.get('sezon'))
        
        if request.form.get('przeciwnik'):
            query += " AND Przeciwnik LIKE ?"
            params.append(f"%{request.form.get('przeciwnik')}%")
        
        if request.form.get('liga'):
            query += " AND Liga = ?"
            params.append(request.form.get('liga'))
        
        if request.form.get('miejsce'):
            query += " AND Miejsce = ?"
            params.append(request.form.get('miejsce'))
    
    query += " ORDER BY [Full Date] DESC"
    
    mecze = conn.execute(query, params).fetchall()
    conn.close()
    
    # Simple statistics
    total_matches = len(mecze)
    wins = sum(1 for m in mecze if parse_result(m['Wynik'])[0] > parse_result(m['Wynik'])[1])
    draws = sum(1 for m in mecze if parse_result(m['Wynik'])[0] == parse_result(m['Wynik'])[1])
    losses = total_matches - wins - draws
    
    stats = {
        'total_matches': total_matches,
        'wins': wins,
        'draws': draws,
        'losses': losses
    }
    
    return render_template('results.html', mecze=mecze, stats=stats)

def parse_result(wynik):
    """Parse score string like '2:1' into tuple (2, 1)"""
    try:
        if ':' in wynik:
            home, away = wynik.split(':')
            return (int(home.strip()), int(away.strip()))
        return (0, 0)
    except:
        return (0, 0)

@app.route('/details/<int:match_id>')
def details(match_id):
    conn = get_db_connection()
    match = conn.execute('SELECT * FROM Mecze WHERE Id = ?', (match_id,)).fetchone()
    conn.close()
    
    if match is None:
        return "Match not found", 404
    
    return render_template('details.html', match=match)

@app.route('/export_excel')
def export_excel():
    # Simple export functionality
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM Mecze ORDER BY [Full Date] DESC", conn)
    conn.close()
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Mecze')
    
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='arka_mecze.xlsx'
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)