from flask import Flask, render_template, request, send_file, redirect, url_for, flash, session
import sqlite3
import os
import pandas as pd
from io import BytesIO
import re
from collections import Counter
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail, Message
from auth_utils import AuthManager
from forms import LoginForm, RegistrationForm, ResendConfirmationForm
from email_utils import send_confirmation_email, send_welcome_email
import secrets
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Configuration from environment variables
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['WTF_CSRF_ENABLED'] = True

# Email configuration - supports both development (localhost) and production (Gmail)
if os.getenv('MAIL_USERNAME'):  # Production Gmail configuration
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
    app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False').lower() == 'true'
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
    print(f"📧 Using Gmail SMTP: {app.config['MAIL_USERNAME']}")
else:  # Development localhost configuration
    app.config['MAIL_SERVER'] = 'localhost'
    app.config['MAIL_PORT'] = 1025
    app.config['MAIL_USE_TLS'] = False
    app.config['MAIL_USE_SSL'] = False
    app.config['MAIL_USERNAME'] = None
    app.config['MAIL_PASSWORD'] = None
    app.config['MAIL_DEFAULT_SENDER'] = 'noreply@arka-kalendarium.com'
    print("🔧 Using localhost SMTP for development")

# Initialize extensions
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

csrf = CSRFProtect(app)
mail = Mail(app)

# Initialize auth manager
auth_manager = AuthManager(app.config['SECRET_KEY'])

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['id'])
        self.email = user_data['email']
        self.is_confirmed = user_data['is_confirmed']
        self.created_at = user_data.get('created_at')
        self.last_login = user_data.get('last_login')

@login_manager.user_loader
def load_user(user_id):
    user_data = auth_manager.get_user_by_id(int(user_id))
    if user_data:
        return User(user_data)
    return None

# Define database path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'Kalendarium.db')


# Database connection function
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Fetch distinct filter options
def get_filter_options(conn, column_name):
    query = f"SELECT DISTINCT {column_name} FROM Mecze ORDER BY {column_name} ASC"
    return conn.execute(query).fetchall()

def add_scorer_filter(query, params, scorer_name):
    """
    Adds a filter to find games where a specific player scored a goal.
    """
    # Use SQL LIKE operator to search for the player's name in the Strzelcy column
    query += " AND Strzelcy LIKE ?"
    params.append(f"%{scorer_name}%")
    return query, params

def add_wynik_filter(query, params, wynik_value):
    """
    Adds Wynik filter (Wygrana, Remis, Porażka) to the SQL query.
    """
    if wynik_value == "Wygrana":
        query += " AND CAST(substr(Wynik, 1, instr(Wynik, ':') - 1) AS INTEGER) > CAST(substr(Wynik, instr(Wynik, ':') + 1) AS INTEGER)"
    elif wynik_value == "Remis":
        query += " AND CAST(substr(Wynik, 1, instr(Wynik, ':') - 1) AS INTEGER) = CAST(substr(Wynik, instr(Wynik, ':') + 1) AS INTEGER)"
    elif wynik_value == "Porażka":
        query += " AND CAST(substr(Wynik, 1, instr(Wynik, ':') - 1) AS INTEGER) < CAST(substr(Wynik, instr(Wynik, ':') + 1) AS INTEGER)"
    return query, params

def build_query(filters):
    query = 'SELECT * FROM Mecze WHERE 1=1'
    params = []

    for key, value in filters.items():
        if value and key not in ["Wynik", "Strzelcy", "ExactScore"]:  # Skip Wynik, Strzelcy, ExactScore for separate handling
            if value == "None":  # Convert "None" to NULL handling
                query += f" AND {key} IS NULL"
            elif key == "Data":
                # Normalize input date formats (dd.mm., dd.mm, dd/mm)
                normalized_value = re.sub(r'[./]', '.', value).rstrip('.')
                query += " AND Data LIKE ?"
                params.append(f"{normalized_value}.%")
            elif key in ["Date >=", "Date <="]:
                # Convert filter date formats to 'yyyy-mm-dd' for Full Date comparison
                normalized_value = re.sub(r'[./]', '-', value)
                if len(normalized_value.split('-')) == 2:  # yyyy-mm
                    normalized_value += '-01'  # Default to first day of the month
                query += f" AND `Full Date` {key.split(' ')[1]} ?"
                params.append(normalized_value)
            else:
                query += f" AND {key} = ?"
                params.append(value)

    # Handle Wynik filter
    if "Wynik" in filters and filters["Wynik"]:
        query, params = add_wynik_filter(query, params, filters["Wynik"])

    # Handle Strzelcy (Scorers) filter
    if "Strzelcy" in filters and filters["Strzelcy"]:
        query, params = add_scorer_filter(query, params, filters["Strzelcy"])

    # Handle ExactScore filter (exact score match like "1:0")
    if "ExactScore" in filters and filters["ExactScore"]:
        query += " AND Wynik = ?"
        params.append(filters["ExactScore"])

    return query, params


def calculate_longest_unbeaten_streak(matches):
    """
    Calculates the longest unbeaten streak (win or draw),
    along with the corresponding start and end dates.
    Updated to use enumerate instead of matches.index(match).
    """
    longest_unbeaten_streak = 0
    longest_unbeaten_start_date = None
    longest_unbeaten_end_date = None

    current_unbeaten_streak = 0
    unbeaten_start_date = None

    for i, match in enumerate(matches):
        score = match["Wynik"]
        full_date = match["Full Date"]

        if not score or not full_date:
            # Missing data, break the current unbeaten streak
            current_unbeaten_streak = 0
            continue

        home, away = map(int, score.split(":"))

        # Win or draw => continue the unbeaten streak
        if home >= away:
            # If streak was broken previously, reset the start date
            if current_unbeaten_streak == 0:
                unbeaten_start_date = full_date

            current_unbeaten_streak += 1

            # Update the longest unbeaten streak if needed
            if current_unbeaten_streak > longest_unbeaten_streak:
                longest_unbeaten_streak = current_unbeaten_streak
                longest_unbeaten_start_date = matches[i - current_unbeaten_streak + 1]["Full Date"]
                longest_unbeaten_end_date = full_date
        else:
            # Lost => streak ends
            current_unbeaten_streak = 0

    return longest_unbeaten_streak, longest_unbeaten_start_date, longest_unbeaten_end_date


def calculate_metrics(matches):
    """
    Consolidates the streak calculations (winning streak, scoring streak,
    clean-sheet streak, and winless streak) in a single pass using
    `for i, match in enumerate(matches)`.
    """
    metrics = {
        "num_matches": len(matches),
        "num_wins": 0,
        "num_draws": 0,
        "num_losses": 0,
        "total_first_digits": 0,
        "total_second_digits": 0,
        "home_goals": 0,      # Goals scored at home
        "home_goals_conceded": 0,  # Goals conceded at home
        "away_goals": 0,      # Goals scored away
        "away_goals_conceded": 0,  # Goals conceded away

        # Streak counters
        "longest_streak": 0,   # Longest winning streak
        "longest_streak_start_date": None,
        "longest_streak_end_date": None,

        "scoring_streak": 0,   # Longest consecutive scoring streak
        "longest_scoring_streak_start_date": None,
        "longest_scoring_streak_end_date": None,

        "clean_sheet_streak": 0,
        "longest_clean_sheet_streak_start_date": None,
        "longest_clean_sheet_streak_end_date": None,

        "winless_streak": 0,
        "longest_winless_streak_start_date": None,
        "longest_winless_streak_end_date": None,

        "longest_no_clean_sheet_streak": 0,
        "longest_no_clean_sheet_streak_start_date": None,
        "longest_no_clean_sheet_streak_end_date": None,

        "highest_attendance_home": 0,
        "highest_attendance_home_year": None,
        "highest_attendance_away": 0,
        "highest_attendance_away_year": None,

        # Clean sheets
        "clean_sheet_count": 0,
        "home_clean_sheets": 0,
        "away_clean_sheets": 0,
    }

    # Track the start/end dates for each streak
    longest_streak_dates = {"start": None, "end": None}
    scoring_streak_dates = {"start": None, "end": None}
    clean_sheet_streak_dates = {"start": None, "end": None}
    no_clean_sheet_streak_dates = {"start": None, "end": None}
    winless_streak_dates = {"start": None, "end": None}

    # Current counters
    current_winning_streak = 0
    current_scoring_streak = 0
    current_clean_sheet_streak = 0
    current_winless_streak = 0
    current_no_clean_sheet_streak = 0

    for i, match in enumerate(matches):
        score = match["Wynik"]
        full_date = match["Full Date"]
        frekwencja = match["Frekwencja"]
        miejsce = match["Miejsce"]

        # Track highest attendance for home or away
        if frekwencja and frekwencja != "NULL":
            try:
                freq_int = int(frekwencja)
                if miejsce == "Dom" and freq_int > metrics["highest_attendance_home"]:
                    metrics["highest_attendance_home"] = freq_int
                    metrics["highest_attendance_home_year"] = (
                        full_date.split("-")[0] if full_date else None
                    )
                elif miejsce == "Wyjazd" and freq_int > metrics["highest_attendance_away"]:
                    metrics["highest_attendance_away"] = freq_int
                    metrics["highest_attendance_away_year"] = (
                        full_date.split("-")[0] if full_date else None
                    )
            except ValueError:
                pass

        # Skip if we don't have a valid score or date
        if not score or not full_date:
            # If either is missing, we can't do scoring/streak logic
            continue

        home, away = map(int, score.split(":"))

        # Summation of total goals
        metrics["total_first_digits"] += home
        metrics["total_second_digits"] += away

        # Home/Away breakdown
        if miejsce == "Dom":
            metrics["home_goals"] += home
            metrics["home_goals_conceded"] += away
        elif miejsce == "Wyjazd":
            metrics["away_goals"] += home
            metrics["away_goals_conceded"] += away

        # Determine match outcome
        if home > away:
            # Win
            metrics["num_wins"] += 1
            current_winning_streak += 1

            # If we just got a win, we reset the current winless streak
            current_winless_streak = 0

            # Update longest winning streak
            if current_winning_streak > metrics["longest_streak"]:
                metrics["longest_streak"] = current_winning_streak
                # The start index is (i - current_winning_streak + 1)
                longest_streak_dates["start"] = matches[i - current_winning_streak + 1]["Full Date"]
                longest_streak_dates["end"] = full_date

        elif home == away:
            # Draw
            metrics["num_draws"] += 1

            # Reset winning streak
            current_winning_streak = 0

            # Increase winless streak
            current_winless_streak += 1
            if current_winless_streak > metrics["winless_streak"]:
                metrics["winless_streak"] = current_winless_streak
                winless_streak_dates["start"] = matches[i - current_winless_streak + 1]["Full Date"]
                winless_streak_dates["end"] = full_date

        else:
            # Loss
            metrics["num_losses"] += 1
            # Reset winning streak
            current_winning_streak = 0
            # Increase winless streak
            current_winless_streak += 1
            if current_winless_streak > metrics["winless_streak"]:
                metrics["winless_streak"] = current_winless_streak
                winless_streak_dates["start"] = matches[i - current_winless_streak + 1]["Full Date"]
                winless_streak_dates["end"] = full_date

        # Scoring streak (if we scored at least one goal)
        if home > 0:
            current_scoring_streak += 1
            if current_scoring_streak > metrics["scoring_streak"]:
                metrics["scoring_streak"] = current_scoring_streak
                scoring_streak_dates["start"] = matches[i - current_scoring_streak + 1]["Full Date"]
                scoring_streak_dates["end"] = full_date
        else:
            # No goals => reset scoring streak
            current_scoring_streak = 0

        # Clean sheet (we conceded 0 goals)
        if away == 0:
            metrics["clean_sheet_count"] += 1
            if miejsce == "Dom":
                metrics["home_clean_sheets"] += 1
            elif miejsce == "Wyjazd":
                metrics["away_clean_sheets"] += 1

            # Update clean sheet streak
            current_clean_sheet_streak += 1
            if current_clean_sheet_streak > metrics["clean_sheet_streak"]:
                metrics["clean_sheet_streak"] = current_clean_sheet_streak
                clean_sheet_streak_dates["start"] = matches[i - current_clean_sheet_streak + 1]["Full Date"]
                clean_sheet_streak_dates["end"] = full_date
        else:
            # We conceded => reset clean sheet streak
            current_clean_sheet_streak = 0

    # Assign final streak start/end dates from our local dictionaries
    metrics["longest_streak_start_date"] = longest_streak_dates["start"]
    metrics["longest_streak_end_date"] = longest_streak_dates["end"]

    metrics["longest_scoring_streak_start_date"] = scoring_streak_dates["start"]
    metrics["longest_scoring_streak_end_date"] = scoring_streak_dates["end"]

    metrics["longest_clean_sheet_streak_start_date"] = clean_sheet_streak_dates["start"]
    metrics["longest_clean_sheet_streak_end_date"] = clean_sheet_streak_dates["end"]

    metrics["longest_winless_streak_start_date"] = winless_streak_dates["start"]
    metrics["longest_winless_streak_end_date"] = winless_streak_dates["end"]

    # Also calculate the longest unbeaten streak (win or draw).
    # We keep it in a separate function for clarity:
    longest_unbeaten, unbeaten_start, unbeaten_end = calculate_longest_unbeaten_streak(matches)
    metrics["longest_unbeaten_streak"] = longest_unbeaten
    metrics["longest_unbeaten_start_date"] = unbeaten_start
    metrics["longest_unbeaten_end_date"] = unbeaten_end

    return metrics


# Export data to Excel
def export_to_excel(matches, filename):
    data = [dict(match) for match in matches]
    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Matches')
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# Calculate top scorers
def get_top_scorers(records):
    scorers = []

    for record in records:
        if not record['Strzelcy']:
            continue  # Skip empty
        # Remove parentheses data & split
        cleaned = re.sub(r'\([^)]*\)', '', record['Strzelcy'])
        for scorer in re.split(r'[; ]+', cleaned.strip()):
            scorer = scorer.strip()
            if scorer and not scorer.isdigit():
                scorers.append(scorer)

    goal_counts = Counter(scorers)
    if goal_counts:
        max_goals = max(goal_counts.values())
        top_scorers = [(s, g) for s, g in goal_counts.items() if g == max_goals]
    else:
        top_scorers = [("", "")]

    return top_scorers


def calculate_home_away_matches(matches):
    home_matches = 0
    away_matches = 0
    for match in matches:
        if match["Miejsce"] == "Dom":
            home_matches += 1
        elif match["Miejsce"] != "Dom":
            away_matches += 1
    return home_matches, away_matches


def calculate_home_away_stats(matches):
    """
    Returns the count of (home_wins, home_draws, home_losses, away_wins, away_draws, away_losses).
    """
    home_wins = home_draws = home_losses = 0
    away_wins = away_draws = away_losses = 0

    for match in matches:
        score = match["Wynik"]
        if not score:
            continue

        home, away = map(int, score.split(":"))
        if match["Miejsce"] == "Dom":
            if home > away:
                home_wins += 1
            elif home == away:
                home_draws += 1
            else:
                home_losses += 1
        else:
            if away > home:
                away_losses += 1
            elif away == home:
                away_draws += 1
            else:
                away_wins += 1

    return home_wins, home_draws, home_losses, away_wins, away_draws, away_losses


def calculate_top_scorers_by_location(matches):
    home_scorers = Counter()
    away_scorers = Counter()

    for match in matches:
        if not match["Strzelcy"]:
            continue

        scorers = re.sub(r'\([^)]*\)', '', match["Strzelcy"])
        for scorer in re.split(r'[; ]+', scorers.strip()):
            scorer = scorer.strip()
            if scorer and not scorer.isdigit():
                if match["Miejsce"] == "Dom":
                    home_scorers[scorer] += 1
                else:
                    away_scorers[scorer] += 1

    # Determine top scorers for home and away
    home_top_scorer = max(home_scorers.items(), key=lambda x: x[1], default=("", 0))
    away_top_scorer = max(away_scorers.items(), key=lambda x: x[1], default=("", 0))

    return home_top_scorer, away_top_scorer


def check_column_visibility(matches):
    """
    Check which columns have data in the filtered results.
    Returns a dictionary indicating which columns should be visible.
    """
    if not matches:
        return {}
    
    visibility = {
        'Strzelcy': False,
        'Frekwencja': False,
        'Sedzia': False
    }
    
    for match in matches:
        # Check Strzelcy column - sqlite3.Row uses dictionary-style access
        if match['Strzelcy'] and str(match['Strzelcy']).strip():
            visibility['Strzelcy'] = True
        
        # Check Frekwencja column  
        if match['Frekwencja'] and match['Frekwencja'] not in [None, '', 'NULL']:
            visibility['Frekwencja'] = True
        
        # Check Sedzia column
        if match['sedzia'] and str(match['sedzia']).strip():
            visibility['Sedzia'] = True
        
        # If all columns have data, no need to continue checking
        if all(visibility.values()):
            break
    
    return visibility


@app.route('/')
def index():
    conn = get_db_connection()
    try:
        filters = {
            "seasons": get_filter_options(conn, 'Sezon'),
            "opponents": get_filter_options(conn, 'Przeciwnik'),
            "leagues": get_filter_options(conn, 'Liga'),
            "places": get_filter_options(conn, 'Miejsce'),
        }
    finally:
        conn.close()
    return render_template('index.html', **filters)


@app.route('/results', methods=['GET', 'POST'])
def results():
    conn = get_db_connection()
    try:
        filters = {
            "Sezon": request.args.get('season', ''),
            "Przeciwnik": request.args.get('opponent', ''),
            "Liga": request.args.get('league', ''),
            "Miejsce": request.args.get('place', ''),
            "Date >=": request.args.get('from_date', ''),
            "Date <=": request.args.get('to_date', ''),
            "Data": request.args.get('date', '') if request.args.get('date') != 'None' else None,
            "ExactScore": request.args.get('result', ''),
            "Kolejka": request.args.get('kolejka', ''),
            "Rok": request.args.get('rok', ''),
            "Strzelcy": request.args.get('scorer', ''),
            "Wynik": request.args.get('wynik', ''),
            "sedzia": request.args.get('referee', '')
        }

        query, params = build_query(filters)
        query += " ORDER BY `Full Date` ASC"
        matches = conn.execute(query, params).fetchall()

        # Calculate metrics in one pass
        metrics = calculate_metrics(matches)

        # Top scorers overall
        top_scorers = get_top_scorers(matches)

        # Home/away stats
        home_wins, home_draws, home_losses, away_wins, away_draws, away_losses = calculate_home_away_stats(matches)
        home_matches, away_matches = calculate_home_away_matches(matches)

        # Home/away top scorers
        home_top_scorer, away_top_scorer = calculate_top_scorers_by_location(matches)

        # Check which columns have data in filtered results
        column_visibility = check_column_visibility(matches)

        # Fetch filters for dropdowns
        seasons = get_filter_options(conn, 'Sezon')
        opponents = get_filter_options(conn, 'Przeciwnik')
        leagues = get_filter_options(conn, 'Liga')
        places = get_filter_options(conn, 'Miejsce')
        referees = get_filter_options(conn, 'sedzia')

    finally:
        conn.close()

    return render_template(
        'results.html',
        matches=matches,
        top_scorers=top_scorers,
        home_wins=home_wins,
        home_draws=home_draws,
        home_losses=home_losses,
        away_wins=away_wins,
        away_draws=away_draws,
        away_losses=away_losses,
        home_matches=home_matches,
        away_matches=away_matches,
        home_top_scorer=home_top_scorer,
        away_top_scorer=away_top_scorer,
        **metrics,
        seasons=seasons,
        opponents=opponents,
        leagues=leagues,
        places=places,
        referees=referees,
        # Pass current filter values for export form
        current_filters=request.args,
        # Pass column visibility information
        column_visibility=column_visibility
    )


@app.route('/export_all_xls', methods=['GET'])
def export_all_xls():
    conn = get_db_connection()
    try:
        matches = conn.execute('SELECT * FROM Mecze').fetchall()
    finally:
        conn.close()

    return export_to_excel(matches, "Wszystkie_mecze.xlsx")


@app.route('/export_xls', methods=['GET'])
def export_xls():
    conn = get_db_connection()
    try:
        filters = {
            "Sezon": request.args.get('season', ''),
            "Przeciwnik": request.args.get('opponent', ''),
            "Liga": request.args.get('league', ''),
            "Miejsce": request.args.get('place', ''),
            "Date >=": request.args.get('from_date', ''),
            "Date <=": request.args.get('to_date', ''),
            "Data": request.args.get('date', '') if request.args.get('date') != 'None' else None,
            "ExactScore": request.args.get('result', ''),
            "Kolejka": request.args.get('kolejka', ''),
            "Rok": request.args.get('rok', ''),
            "Strzelcy": request.args.get('scorer', ''),
            "Wynik": request.args.get('wynik', ''),
            "sedzia": request.args.get('referee', '')
        }

        query, params = build_query(filters)
        matches = conn.execute(query, params).fetchall()

    finally:
        conn.close()

    return export_to_excel(matches, "filtered_matches.xlsx")

@app.route('/details/<int:match_id>')
def match_details(match_id):
    conn = get_db_connection()
    try:
        # Fetch match details
        query = """
        SELECT Sezon, Kolejka, `Full date`, Wynik, Miejsce, Przeciwnik, Liga,
               Frekwencja, gol_przeciwnika, sklad_arka, sklad_przeciwnika, sedzia, Strzelcy
        FROM Mecze
        WHERE Id = ?
        """
        match = conn.execute(query, (match_id,)).fetchone()
        if not match:
            return render_template('404.html'), 404
        
        # Convert match data to dictionary for easier handling
        match = dict(match)

        # Split lineups and scorers into lists
        arka_players = match['sklad_arka'].split(';') if match['sklad_arka'] else []
        opponent_players = match['sklad_przeciwnika'].split(';') if match['sklad_przeciwnika'] else []
        scorers = match['Strzelcy'].split(';') if match['Strzelcy'] else []
        opponent_goals = match['gol_przeciwnika'].split(';') if match['gol_przeciwnika'] else []

        # Calculate the maximum length for each section
        max_length_lineups = max(len(arka_players), len(opponent_players))
        max_length_scorers = max(len(scorers), len(opponent_goals))

        # Process score and team order based on match location
        if match['Miejsce'] == 'Wyjazd':  # Away game
            # Flip the score for away games (database stores Arka:Opponent, display as Opponent:Arka)
            if match['Wynik']:
                arka_goals, opponent_goals = match['Wynik'].split(':')
                match['display_score'] = f"{opponent_goals}:{arka_goals}"
            else:
                match['display_score'] = match['Wynik']
            
            # For away games, flip the order in tables (opponent first, then Arka)
            match['arka_players'] = opponent_players
            match['opponent_players'] = arka_players
            match['scorers'] = opponent_goals
            match['opponent_goals'] = scorers
        else:  # Home game
            # Keep original order for home games
            match['display_score'] = match['Wynik']
            match['arka_players'] = arka_players
            match['opponent_players'] = opponent_players
            match['scorers'] = scorers
            match['opponent_goals'] = opponent_goals
        
        match['max_length_lineups'] = max_length_lineups
        match['max_length_scorers'] = max_length_scorers
    finally:
        conn.close()

    return render_template('details.html', match=match)


# Authentication Routes
@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        success, result = auth_manager.create_user(form.email.data, form.password.data)
        if success:
            # Send confirmation email
            email_sent, email_msg = send_confirmation_email(mail, form.email.data, result)
            if email_sent:
                flash('Registration successful! Please check your email to confirm your account.', 'success')
            else:
                flash('Registration successful, but email failed to send. Please contact support.', 'warning')
                # For development, show the token
                flash(f'Confirmation token (dev): {result}', 'info')
            return redirect(url_for('login'))
        else:
            flash(f'Registration failed: {result}', 'error')
    
    return render_template('auth/register.html', form=form)

@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user_data, error = auth_manager.authenticate_user(form.email.data, form.password.data)
        if user_data:
            user = User(user_data)
            login_user(user, remember=form.remember_me.data)
            flash('Logged in successfully!', 'success')
            
            # Redirect to next page if specified
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash(error, 'error')
    
    return render_template('auth/login.html', form=form)

@app.route('/auth/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/auth/confirm/<token>')
def confirm_email(token):
    if current_user.is_authenticated and current_user.is_confirmed:
        flash('Account already confirmed.', 'info')
        return redirect(url_for('index'))
    
    success, message = auth_manager.confirm_email(token)
    if success:
        flash(message, 'success')
        # Get the confirmed email to send welcome email
        email = auth_manager.confirm_token(token)
        if email:
            send_welcome_email(mail, email)
        return redirect(url_for('login'))
    else:
        flash(message, 'error')
        return redirect(url_for('register'))

@app.route('/auth/resend', methods=['GET', 'POST'])
def resend_confirmation():
    if current_user.is_authenticated and current_user.is_confirmed:
        return redirect(url_for('index'))
    
    form = ResendConfirmationForm()
    if form.validate_on_submit():
        success, result = auth_manager.resend_confirmation(form.email.data)
        if success:
            # Send new confirmation email
            email_sent, email_msg = send_confirmation_email(mail, form.email.data, result)
            if email_sent:
                flash('New confirmation email sent! Check your email.', 'success')
            else:
                flash('Token generated but email failed to send. Please contact support.', 'warning')
                # For development, show the token
                flash(f'Confirmation token (dev): {result}', 'info')
            return redirect(url_for('login'))
        else:
            flash(f'Error: {result}', 'error')
    
    return render_template('auth/resend.html', form=form)

if __name__ == '__main__':
    app.run(debug=True)
