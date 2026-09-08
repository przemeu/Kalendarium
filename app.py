from flask import Flask, render_template, request, send_file
import sqlite3
import os
import pandas as pd
from io import BytesIO
import re
import json
from collections import Counter
import secrets
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))

def is_post_2008(season_str):
    if not season_str:
        return False
    try:
        season_str = str(season_str)
        if '/' in season_str:
            year_part = season_str.split('/')[0]
        else:
            year_part = season_str
        return int(year_part) >= 2008
    except ValueError:
        return False

def get_friendly_league_name(league, season):
    if not league:
        return ""
    
    post_2008 = is_post_2008(season)
    
    # Dictionary mappings
    if post_2008:
        mapping = {
            'I': 'Ekstraklasa',
            'II': 'Pierwsza Liga',
            'III': 'Druga Liga',
            'IV': 'Trzecia Liga',
            'V': 'Czwarta Liga',
            'VI': 'Piąta Liga'
        }
    else:
        mapping = {
            'I': '1 liga',
            'II': '2 liga',
            'III': '3 liga',
            'IV': '4 liga',
            'V': '5 liga',
            'VI': '6 liga'
        }
        
    # Cup mappings (common for both eras)
    cup_mapping = {
        'PP': 'Puchar Polski',
        'PL': 'Puchar Ligi',
        'PE': 'Puchar Ekstraklasy',
        'B': 'Baraże'
    }
    
    if league in mapping:
        return mapping[league]
    if league in cup_mapping:
        return cup_mapping[league]
        
    return league

def get_logo_url(team_name):
    if not team_name:
        return None
    try:
        mapping_path = os.path.join(app.static_folder, 'logos', 'mapping.json')
        if os.path.exists(mapping_path):
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
                filename = mapping.get(team_name)
                if filename:
                    return f"/static/logos/{filename}"
    except Exception as e:
        print(f"Error loading logo mapping: {e}")
    return None

def process_scorers(scorers_str):
    if not scorers_str:
        return []
    parts = scorers_str.split(';')
    processed = []
    for part in parts:
        part = part.strip()
        if not part: continue
        
        # Robust regex matching the minute and any suffix
        min_match = re.search(r'\s+(\d+)\s*(\(?[a-zA-ZąęćłńóśźżĄĆĘŁŃÓŚŹŻ\']+\)?|\')?$', part)
        
        # Check for own goal, notes, or bracketed info
        is_note = False
        if not min_match:
            if (part.startswith('(') and part.endswith(')')) or re.search(r'\b\d*s\)?$', part) or '(s)' in part or part.lower() == 'walkower' or len(part) > 25:
                is_note = True
        else:
            if part.startswith('(') and part.endswith(')'):
                is_note = True
                
        if is_note:
            processed.append({'text': part, 'is_link': False})
            continue
            
        # Clean name using the matched group
        if min_match:
            name_clean = part[:min_match.start()].strip()
        else:
            name_clean = part.strip('()')
        
        processed.append({'text': part, 'name': name_clean, 'is_link': True})
    return processed

def process_scorers_html(scorers_str):
    if not scorers_str:
        return []
    parts = scorers_str.split(';')
    tokens = []
    
    for idx, part in enumerate(parts):
        part = part.strip()
        if not part: continue
        
        # Check for own goal with name and minute, e.g. "(Lebedyński 21s)"
        own_goal_match = re.match(r'^\((.*?)\s+(\d+)s\)$', part)
        if own_goal_match:
            player_name, minute_val = own_goal_match.groups()
            if idx > 0:
                tokens.append({'type': 'separator', 'text': '; '})
            tokens.append({'type': 'text', 'text': '('})
            tokens.append({'type': 'player', 'text': player_name, 'url': '/results?scorer=s)'})
            tokens.append({'type': 'space', 'text': ' '})
            tokens.append({'type': 'minute', 'text': f"{minute_val}s", 'url': f'/results?goal_minute={minute_val}'})
            tokens.append({'type': 'text', 'text': ')'})
            continue

        # Check for own goal with name but no minute, e.g. "(Król s)"
        own_goal_no_min = re.match(r'^\((.*?)\s+s\)$', part)
        if own_goal_no_min:
            player_name = own_goal_no_min.group(1)
            if idx > 0:
                tokens.append({'type': 'separator', 'text': '; '})
            tokens.append({'type': 'text', 'text': '('})
            tokens.append({'type': 'player', 'text': player_name, 'url': '/results?scorer=s)'})
            tokens.append({'type': 'text', 'text': ' s)'})
            continue
            
        # Check if it is a special note, own goal (s), walkover, or bracketed info
        if (part.startswith('(') and part.endswith(')')) or re.search(r'\b\d*s\)?$', part) or '(s)' in part or part.lower() == 'walkower' or len(part) > 30:
            if idx > 0:
                tokens.append({'type': 'separator', 'text': '; '})
            tokens.append({'type': 'text', 'text': part})
            continue
            
        # Check if the part is just a minute (e.g., "70" or "90k" or "90'")
        is_just_minute = re.match(r'^\d+\s*(\(?[a-zA-ZąęćłńóśźżĄĆĘŁŃÓŚŹŻ\']+\)?|\')?$', part) is not None
        
        if is_just_minute:
            # It's a minute belonging to the last seen player
            min_digits = re.search(r'\d+', part).group()
            tokens.append({'type': 'separator', 'text': '; '})
            tokens.append({'type': 'minute', 'text': part, 'url': f'/results?goal_minute={min_digits}'})
        else:
            # It has a name and possibly a minute, e.g., "Filipiak 38" or "Filipiak"
            min_match = re.search(r'\s+(\d+)\s*(\(?[a-zA-ZąęćłńóśźżĄĆĘŁŃÓŚŹŻ\']+\)?|\')?$', part)
            if min_match:
                minute_part = part[min_match.start(1):].strip()
                name_part = part[:min_match.start()].strip()
                min_digits = min_match.group(1)
            else:
                minute_part = None
                name_part = part
                min_digits = None
                
            name_clean = name_part.strip('()')
            
            # Add separator between different players
            if idx > 0:
                tokens.append({'type': 'separator', 'text': '; '})
                
            # Add player token
            tokens.append({'type': 'player', 'text': name_part, 'url': f'/results?scorer={name_clean}'})
            
            # Add minute token if present
            if minute_part:
                tokens.append({'type': 'space', 'text': ' '})
                tokens.append({'type': 'minute', 'text': minute_part, 'url': f'/results?goal_minute={min_digits}'})
                
    return tokens

app.jinja_env.globals.update(is_post_2008=is_post_2008, get_logo_url=get_logo_url, process_scorers=process_scorers, process_scorers_html=process_scorers_html, get_friendly_league_name=get_friendly_league_name)

def process_squad(squad_str):
    if not squad_str:
        return []
    players = squad_str.split(';')
    processed = []
    
    last_off_minute = None
    
    for player in players:
        player = player.strip()
        if not player:
            continue
            
        match_off_old = re.match(r'^(.*?)\s+(\d+)$', player)
        match_on_old = re.match(r'^(\d+)\s+(.*)$', player)
        match_off_new = re.match(r'^(.*?)\s+\((\d+)\\?\'\)$', player)
        
        if match_off_old:
            name, minute = match_off_old.groups()
            processed.append({'name': name, 'status': 'off', 'minute': minute})
            last_off_minute = minute
        elif match_on_old:
            minute, name = match_on_old.groups()
            processed.append({'name': name, 'status': 'on', 'minute': minute})
            last_off_minute = None
        elif match_off_new:
            name, minute = match_off_new.groups()
            processed.append({'name': name, 'status': 'off', 'minute': minute})
            last_off_minute = minute
        else:
            if last_off_minute:
                processed.append({'name': player, 'status': 'on', 'minute': last_off_minute})
                last_off_minute = None
            else:
                processed.append({'name': player, 'status': 'start', 'minute': None})
                
    return processed

app.jinja_env.globals.update(process_squad=process_squad)

# Define database path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'Kalendarium.db')


def regexp(expr, item):
    if item is None:
        return False
    reg = re.compile(expr, re.IGNORECASE)
    return reg.search(str(item)) is not None

# Database connection function
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, regexp)
    return conn


# Fetch distinct filter options
PL_MAP = str.maketrans("ĄĆĘŁŃÓŚŹŻąćęłńóśźż", "ACELNOSZZacelnoszz")

def get_filter_options(conn, column_name, order="ASC"):
    query = f"SELECT DISTINCT {column_name} FROM Mecze ORDER BY {column_name} {order}"
    rows = conn.execute(query).fetchall()
    if column_name == 'sedzia':
        def get_last_name(r):
            val = r['sedzia']
            if not val:
                return ""
            name_part = val.split('(')[0].strip()
            names = name_part.split()
            if not names:
                return ""
            last = names[-1]
            return last.translate(PL_MAP).lower()
        rows = sorted(rows, key=get_last_name)
    return rows

def add_scorer_filter(query, params, scorer_name):
    """
    Adds a filter to find games where a specific player scored a goal.
    """
    # Use SQL LIKE operator to search for the player's name in both Strzelcy and gol_przeciwnika columns
    query += " AND (Strzelcy LIKE ? OR gol_przeciwnika LIKE ?)"
    params.extend([f"%{scorer_name}%", f"%{scorer_name}%"])
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

def parse_kolejka_filter(raw_input):
    """
    Parses round/kolejka filter input supporting:
    - Single round: '5' or 'PP'
    - Multiple comma/semicolon/lub-separated rounds: '1, 3, 7'
    - Numeric ranges: '21-34', '1-5'
    - Mixed combinations: '1, 3, 7, 21-34'
    """
    if not raw_input:
        return []
    
    cleaned = re.sub(r'\b(?:lub|or|i)\b', ',', str(raw_input), flags=re.IGNORECASE)
    cleaned = cleaned.replace(';', ',')
    
    parts = [p.strip() for p in cleaned.split(',') if p.strip()]
    results = []
    
    for part in parts:
        range_match = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                start, end = end, start
            for num in range(start, end + 1):
                results.append(str(num))
        else:
            results.append(part)
            
    seen = set()
    unique_results = []
    for r in results:
        if r not in seen:
            seen.add(r)
            unique_results.append(r)
            
    return unique_results

def build_query(filters):
    query = 'SELECT * FROM Mecze WHERE 1=1'
    params = []

    for key, value in filters.items():
        if value and key not in ["Wynik", "Strzelcy", "ExactScore", "Player", "goal_minute", "Kolejka"]:  # Skip special handling keys
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
        normalized_score = filters["ExactScore"].strip().replace(' ', '').replace('-', ':')
        query += " AND Wynik = ?"
        params.append(normalized_score)

    # Handle Player filter
    if "Player" in filters and filters["Player"]:
        query += " AND (sklad_arka LIKE ? OR sklad_przeciwnika LIKE ?)"
        params.extend([f"%{filters['Player']}%", f"%{filters['Player']}%"])

    # Handle goal_minute filter
    if "goal_minute" in filters and filters["goal_minute"]:
        min_match = re.search(r'\d+', filters["goal_minute"])
        if min_match:
            minute_val = min_match.group()
            # Regex pattern to match exact minute (e.g. 20, 20k, 20s, 20')
            pattern = rf'(?:\s|^){minute_val}(?:k|s|\'|;|$)'
            query += " AND Strzelcy REGEXP ?"
            params.append(pattern)

    # Handle Kolejka filter (supports single round, comma-separated list, or ranges like "21-34")
    if "Kolejka" in filters and filters["Kolejka"]:
        kolejki = parse_kolejka_filter(filters["Kolejka"])
        if kolejki:
            placeholders = ', '.join(['?'] * len(kolejki))
            query += f" AND Kolejka IN ({placeholders})"
            params.extend(kolejki)

    return query, params


def get_field(m, *keys, default=None):
    """
    Safely retrieves a field value from a dict or sqlite3.Row object.
    """
    for k in keys:
        try:
            val = m[k]
            if val is not None:
                return val
        except (IndexError, KeyError, TypeError):
            pass
    return default


def parse_score(score):
    """
    Safely parses score string into (home, away) tuple of integers.
    Returns (None, None) if score is invalid.
    """
    if not score:
        return None, None
    m = re.search(r'(\d+)\s*:\s*(\d+)', str(score))
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


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
        score = get_field(match, "Wynik")
        full_date = get_field(match, "Full Date", "Full date")

        if not score or not full_date:
            # Missing data, break the current unbeaten streak
            current_unbeaten_streak = 0
            continue

        home, away = parse_score(score)
        if home is None or away is None:
            current_unbeaten_streak = 0
            continue

        # Win or draw => continue the unbeaten streak
        if home >= away:
            # If streak was broken previously, reset the start date
            if current_unbeaten_streak == 0:
                unbeaten_start_date = full_date

            current_unbeaten_streak += 1

            # Update the longest unbeaten streak if needed
            if current_unbeaten_streak > longest_unbeaten_streak:
                longest_unbeaten_streak = current_unbeaten_streak
                start_m = matches[i - current_unbeaten_streak + 1]
                longest_unbeaten_start_date = get_field(start_m, "Full Date", "Full date")
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
        "average_attendance_home": None,
        "highest_attendance_away": 0,
        "highest_attendance_away_year": None,
        "average_attendance_away": None,

        # Clean sheets
        "clean_sheet_count": 0,
        "home_clean_sheets": 0,
        "away_clean_sheets": 0,

        # Biggest Win / Loss
        "biggest_win_diff": -1,
        "biggest_win_match": None,
        "biggest_loss_diff": 1,
        "biggest_loss_match": None,
    }

    # Track the start/end dates for each streak
    longest_streak_dates = {"start": None, "end": None}
    scoring_streak_dates = {"start": None, "end": None}
    clean_sheet_streak_dates = {"start": None, "end": None}
    no_clean_sheet_streak_dates = {"start": None, "end": None}
    winless_streak_dates = {"start": None, "end": None}

    # New tracking structures
    referees = {}
    scorelines = {"Total": {}, "Dom": {}, "Wyjazd": {}}
    opponents = {}

    home_attendance_list = []
    away_attendance_list = []

    # Current counters
    current_winning_streak = 0
    current_scoring_streak = 0
    current_clean_sheet_streak = 0
    current_winless_streak = 0
    current_no_clean_sheet_streak = 0

    for i, match in enumerate(matches):
        score = get_field(match, "Wynik")
        full_date = get_field(match, "Full Date", "Full date")
        frekwencja = get_field(match, "Frekwencja")
        miejsce = get_field(match, "Miejsce")

        # Track highest and average attendance for home or away
        if frekwencja and frekwencja != "NULL":
            try:
                freq_int = int(frekwencja)
                if freq_int > 0:
                    if miejsce == "Dom":
                        home_attendance_list.append(freq_int)
                        if freq_int > metrics["highest_attendance_home"]:
                            metrics["highest_attendance_home"] = freq_int
                            metrics["highest_attendance_home_year"] = (
                                full_date.split("-")[0] if full_date else None
                            )
                    elif miejsce == "Wyjazd":
                        away_attendance_list.append(freq_int)
                        if freq_int > metrics["highest_attendance_away"]:
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

        home, away = parse_score(score)
        if home is None or away is None:
            continue

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

        # Biggest win / loss tracking
        goal_diff = home - away
        if goal_diff > 0 and goal_diff > metrics["biggest_win_diff"]:
            metrics["biggest_win_diff"] = goal_diff
            metrics["biggest_win_match"] = match
        
        if goal_diff < 0 and goal_diff < metrics["biggest_loss_diff"]:
            metrics["biggest_loss_diff"] = goal_diff
            metrics["biggest_loss_match"] = match

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
                start_m = matches[i - current_winning_streak + 1]
                longest_streak_dates["start"] = get_field(start_m, "Full Date", "Full date")
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
                start_m = matches[i - current_winless_streak + 1]
                winless_streak_dates["start"] = get_field(start_m, "Full Date", "Full date")
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
                start_m = matches[i - current_winless_streak + 1]
                winless_streak_dates["start"] = get_field(start_m, "Full Date", "Full date")
                winless_streak_dates["end"] = full_date

        # Scoring streak (if we scored at least one goal)
        if home > 0:
            current_scoring_streak += 1
            if current_scoring_streak > metrics["scoring_streak"]:
                metrics["scoring_streak"] = current_scoring_streak
                start_m = matches[i - current_scoring_streak + 1]
                scoring_streak_dates["start"] = get_field(start_m, "Full Date", "Full date")
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
                start_m = matches[i - current_clean_sheet_streak + 1]
                clean_sheet_streak_dates["start"] = get_field(start_m, "Full Date", "Full date")
                clean_sheet_streak_dates["end"] = full_date
        else:
            # We conceded => reset clean sheet streak
            current_clean_sheet_streak = 0

        # No clean sheet streak (conceded > 0 goals)
        if away > 0:
            current_no_clean_sheet_streak += 1
            if current_no_clean_sheet_streak > metrics["longest_no_clean_sheet_streak"]:
                metrics["longest_no_clean_sheet_streak"] = current_no_clean_sheet_streak
                start_m = matches[i - current_no_clean_sheet_streak + 1]
                no_clean_sheet_streak_dates["start"] = get_field(start_m, "Full Date", "Full date")
                no_clean_sheet_streak_dates["end"] = full_date
        else:
            current_no_clean_sheet_streak = 0
            
        # Track Referee
        referee = get_field(match, "sedzia")
        if referee and referee != "NULL" and str(referee).strip():
            referee = str(referee).strip()
            if referee not in referees:
                referees[referee] = {"games": 0, "wins": 0, "draws": 0, "losses": 0}
            referees[referee]["games"] += 1
            if home > away:
                referees[referee]["wins"] += 1
            elif home == away:
                referees[referee]["draws"] += 1
            else:
                referees[referee]["losses"] += 1
                
        # Track Scoreline
        if score not in scorelines["Total"]:
            scorelines["Total"][score] = 0
        scorelines["Total"][score] += 1
        
        if miejsce in ["Dom", "Wyjazd"]:
            if score not in scorelines[miejsce]:
                scorelines[miejsce][score] = 0
            scorelines[miejsce][score] += 1

        # Track Opponents
        opp = match["Przeciwnik"] if "Przeciwnik" in match.keys() else None
        if opp and opp != "NULL" and opp.strip():
            opp = opp.strip()
            if opp not in opponents:
                opponents[opp] = {"games": 0, "wins": 0, "draws": 0, "losses": 0, "goals_scored": 0, "goals_conceded": 0}
            opponents[opp]["games"] += 1
            opponents[opp]["goals_scored"] += home
            opponents[opp]["goals_conceded"] += away
            if home > away:
                opponents[opp]["wins"] += 1
            elif home == away:
                opponents[opp]["draws"] += 1
            else:
                opponents[opp]["losses"] += 1

    # Calculate Most Common Scorelines
    metrics["most_common_score_total"] = max(scorelines["Total"].items(), key=lambda x: x[1])[0] if scorelines["Total"] else None
    metrics["most_common_score_total_count"] = scorelines["Total"].get(metrics["most_common_score_total"], 0)
    metrics["most_common_score_home"] = max(scorelines["Dom"].items(), key=lambda x: x[1])[0] if scorelines["Dom"] else None
    metrics["most_common_score_home_count"] = scorelines["Dom"].get(metrics["most_common_score_home"], 0)
    metrics["most_common_score_away"] = max(scorelines["Wyjazd"].items(), key=lambda x: x[1])[0] if scorelines["Wyjazd"] else None
    metrics["most_common_score_away_count"] = scorelines["Wyjazd"].get(metrics["most_common_score_away"], 0)
    
    # Calculate Favorite Referee
    if referees:
        best_ref = max(referees.items(), key=lambda x: (x[1]["games"], x[1]["wins"]))
        metrics["favorite_referee"] = best_ref[0]
        metrics["favorite_referee_stats"] = best_ref[1]
    else:
        metrics["favorite_referee"] = None
        metrics["favorite_referee_stats"] = None
        
    # Calculate Best/Worst Opponents
    if opponents:
        # Best opponent: Arka must have won at least once
        best_candidates = {k: v for k, v in opponents.items() if v["wins"] > 0}
        if best_candidates:
            best_opp = max(best_candidates.items(), key=lambda x: (x[1]["wins"], x[1]["goals_scored"] - x[1]["goals_conceded"]))
            metrics["best_opponent"] = best_opp[0]
            metrics["best_opponent_stats"] = best_opp[1]
        else:
            metrics["best_opponent"] = None
            metrics["best_opponent_stats"] = None
            
        # Worst opponent: Arka must have lost at least once
        worst_candidates = {k: v for k, v in opponents.items() if v["losses"] > 0}
        if worst_candidates:
            worst_opp = max(worst_candidates.items(), key=lambda x: (x[1]["losses"], -(x[1]["goals_scored"] - x[1]["goals_conceded"])))
            metrics["worst_opponent"] = worst_opp[0]
            metrics["worst_opponent_stats"] = worst_opp[1]
        else:
            metrics["worst_opponent"] = None
            metrics["worst_opponent_stats"] = None
    else:
        metrics["best_opponent"] = None
        metrics["best_opponent_stats"] = None
        metrics["worst_opponent"] = None
        metrics["worst_opponent_stats"] = None
    metrics["longest_streak_start_date"] = longest_streak_dates["start"]
    metrics["longest_streak_end_date"] = longest_streak_dates["end"]

    metrics["longest_scoring_streak_start_date"] = scoring_streak_dates["start"]
    metrics["longest_scoring_streak_end_date"] = scoring_streak_dates["end"]

    metrics["longest_clean_sheet_streak_start_date"] = clean_sheet_streak_dates["start"]
    metrics["longest_clean_sheet_streak_end_date"] = clean_sheet_streak_dates["end"]

    metrics["longest_winless_streak_start_date"] = winless_streak_dates["start"]
    metrics["longest_winless_streak_end_date"] = winless_streak_dates["end"]

    metrics["longest_no_clean_sheet_streak_start_date"] = no_clean_sheet_streak_dates["start"]
    metrics["longest_no_clean_sheet_streak_end_date"] = no_clean_sheet_streak_dates["end"]

    # Also calculate the longest unbeaten streak (win or draw).
    # We keep it in a separate function for clarity:
    longest_unbeaten, unbeaten_start, unbeaten_end = calculate_longest_unbeaten_streak(matches)
    metrics["longest_unbeaten_streak"] = longest_unbeaten
    metrics["longest_unbeaten_start_date"] = unbeaten_start
    metrics["longest_unbeaten_end_date"] = unbeaten_end

    # Calculate average attendances
    if home_attendance_list:
        metrics["average_attendance_home"] = round(sum(home_attendance_list) / len(home_attendance_list))
    if away_attendance_list:
        metrics["average_attendance_away"] = round(sum(away_attendance_list) / len(away_attendance_list))

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
            continue
        for scorer in process_scorers(record['Strzelcy']):
            if scorer.get('is_link') and scorer.get('name'):
                scorers.append(scorer['name'])

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
        home, away = parse_score(score)
        if home is None or away is None:
            continue
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

        for scorer in process_scorers(match["Strzelcy"]):
            if scorer.get('is_link') and scorer.get('name'):
                if match["Miejsce"] == "Dom":
                    home_scorers[scorer['name']] += 1
                else:
                    away_scorers[scorer['name']] += 1

    # Determine top scorers for home and away
    home_top_scorer = max(home_scorers.items(), key=lambda x: x[1], default=("", 0))
    away_top_scorer = max(away_scorers.items(), key=lambda x: x[1], default=("", 0))

    return home_top_scorer, away_top_scorer


def check_column_visibility(matches):
    """
    Returns True for all columns to ensure the table layout remains consistent,
    even if the currently filtered matches have no data for these columns.
    """
    return {
        'Strzelcy': True,
        'Frekwencja': True,
        'Sedzia': True
    }


from flask import redirect, url_for

@app.route('/')
def index():
    return redirect(url_for('results'))


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
            "Strzelcy": 's)' if request.args.get('scorer', '').lower() in ['bramki samobójcze', 'samobójcze', 'samobój', 's)', 'samobójcza'] else request.args.get('scorer', ''),
            "Wynik": request.args.get('wynik', ''),
            "sedzia": request.args.get('referee', ''),
            "Player": request.args.get('player', ''),
            "goal_minute": request.args.get('goal_minute', '')
        }

        query, params = build_query(filters)
        sort_order = request.args.get('sort_order', 'asc').upper()
        if sort_order not in ['ASC', 'DESC']:
            sort_order = 'ASC'
            
        query += f" ORDER BY `Full Date` {sort_order}"
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
        seasons = get_filter_options(conn, 'Sezon', 'DESC')
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
        selected_ids_str = request.args.get('selected_ids', '')
        if selected_ids_str:
            ids = [int(x) for x in selected_ids_str.split(',') if x.strip().isdigit()]
            if ids:
                placeholders = ','.join(['?' for _ in ids])
                query = f'SELECT * FROM Mecze WHERE Id IN ({placeholders}) ORDER BY `Full Date` ASC'
                matches = conn.execute(query, ids).fetchall()
                return export_to_excel(matches, "zaznaczone_mecze.xlsx")

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
            "Strzelcy": 's)' if request.args.get('scorer', '').lower() in ['bramki samobójcze', 'samobójcze', 'samobój', 's)', 'samobójcza'] else request.args.get('scorer', ''),
            "Wynik": request.args.get('wynik', ''),
            "sedzia": request.args.get('referee', ''),
            "Player": request.args.get('player', ''),
            "goal_minute": request.args.get('goal_minute', '')
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
               Frekwencja, gol_przeciwnika, sklad_arka, sklad_przeciwnika, sedzia, Strzelcy,
               kartki_arka, kartki_przeciwnik
        FROM Mecze
        WHERE Id = ?
        """
        match = conn.execute(query, (match_id,)).fetchone()
        if not match:
            return render_template('404.html'), 404
        
        # Convert match data to dictionary for easier handling
        match = dict(match)

        # Split lineups and scorers into lists
        arka_players = process_squad(match['sklad_arka'])
        opponent_players = process_squad(match['sklad_przeciwnika'])
        scorers = match['Strzelcy'].split(';') if match['Strzelcy'] else []
        opponent_goals = match['gol_przeciwnika'].split(';') if match['gol_przeciwnika'] else []

        import json
        try:
            arka_cards_raw = json.loads(match.get('kartki_arka') or '[]')
            opp_cards_raw = json.loads(match.get('kartki_przeciwnik') or '[]')
        except json.JSONDecodeError:
            arka_cards_raw = []
            opp_cards_raw = []

        # Calculate the maximum length for each section
        max_length_lineups = max(len(arka_players), len(opponent_players))
        max_length_scorers = max(len(scorers), len(opponent_goals))

        # Process score and team order based on match location
        if match['Miejsce'] == 'Wyjazd':  # Away game
            # Flip the score for away games (database stores Arka:Opponent, display as Opponent:Arka)
            if match['Wynik']:
                h, a = parse_score(match['Wynik'])
                if h is not None and a is not None:
                    match['display_score'] = f"{a}:{h}"
                else:
                    match['display_score'] = match['Wynik']
            else:
                match['display_score'] = match['Wynik']
            
            # For away games, flip the order in tables (opponent first, then Arka)
            match['arka_players'] = opponent_players
            match['opponent_players'] = arka_players
            match['scorers'] = opponent_goals
            match['opponent_goals'] = scorers
            match['arka_cards'] = opp_cards_raw
            match['opponent_cards'] = arka_cards_raw
        else:  # Home game
            # Keep original order for home games
            match['display_score'] = match['Wynik']
            match['arka_players'] = arka_players
            match['opponent_players'] = opponent_players
            match['scorers'] = scorers
            match['opponent_goals'] = opponent_goals
            match['arka_cards'] = arka_cards_raw
            match['opponent_cards'] = opp_cards_raw
        
        match['max_length_lineups'] = max_length_lineups
        match['max_length_scorers'] = max_length_scorers

        # Parse and build chronological timeline events
        events = []
        
        def parse_goals(goal_list, is_home):
            for goal_str in goal_list:
                goal_str = goal_str.strip()
                if not goal_str:
                    continue
                
                # Skip informational match notes (like penalty shootout scores or extra time results)
                if goal_str.startswith('(') and goal_str.endswith(')') and ('dogrywce' in goal_str or 'karne' in goal_str or re.search(r'\d+:\d+', goal_str)):
                    continue
                
                is_own = False
                orig_str = goal_str
                if goal_str.startswith('(') and goal_str.endswith(')'):
                    inner = goal_str[1:-1].strip()
                    if inner.endswith('s'):
                        is_own = True
                        inner = inner[:-1].strip()
                    goal_str = inner
                
                # Match player name and minute
                match_min = re.search(r'\s+(\d+)(k|s|\')?$', goal_str)
                if match_min:
                    minute = match_min.group(1)
                    suffix = match_min.group(2) or ""
                    player_name = goal_str[:match_min.start()].strip()
                    is_penalty = (suffix == 'k')
                else:
                    minute = ""
                    player_name = goal_str
                    is_penalty = False
                
                event_type = 'own_goal' if is_own else ('penalty' if is_penalty else 'goal')
                events.append({
                    'minute': minute,
                    'type': event_type,
                    'player': player_name,
                    'is_home': is_home,
                    'text': orig_str
                })

        # Process goals (flipped if away in python route above, so match['scorers'] is home goals)
        parse_goals(match['scorers'], is_home=True)
        parse_goals(match['opponent_goals'], is_home=False)

        # Process cards
        for card in (match.get('arka_cards') or []):
            events.append({
                'minute': card.get('minute', ''),
                'type': 'card_red' if card.get('type') == 'red' else 'card_yellow',
                'player': card.get('name', ''),
                'is_home': True,
                'text': f"{card.get('name', '')} {card.get('minute', '')}'"
            })
            
        for card in (match.get('opponent_cards') or []):
            events.append({
                'minute': card.get('minute', ''),
                'type': 'card_red' if card.get('type') == 'red' else 'card_yellow',
                'player': card.get('name', ''),
                'is_home': False,
                'text': f"{card.get('name', '')} {card.get('minute', '')}'"
            })

        # Sort timeline by minute
        def get_min_val(ev):
            min_str = str(ev['minute']).replace("'", "").strip()
            if not min_str:
                return 999
            if '+' in min_str:
                try:
                    return sum(int(p) for p in min_str.split('+'))
                except ValueError:
                    return 999
            try:
                return int(min_str)
            except ValueError:
                return 999
                
        events.sort(key=get_min_val)
        match['events'] = events
    finally:
        conn.close()

    return render_template('details.html', match=match)


@app.route('/results/selected', methods=['POST'])
def selected_results():
    """Display only the manually selected matches with full statistics."""
    selected_ids_str = request.form.get('selected_ids', '')
    ids = [int(x) for x in selected_ids_str.split(',') if x.strip().isdigit()]

    if not ids:
        return render_template(
            'results.html', matches=[], num_matches=0, num_wins=0, num_draws=0,
            num_losses=0, total_first_digits=0, total_second_digits=0,
            home_goals=0, home_goals_conceded=0, away_goals=0, away_goals_conceded=0,
            longest_streak=0, scoring_streak=0, clean_sheet_streak=0, winless_streak=0,
            longest_unbeaten_streak=0, longest_no_clean_sheet_streak=0,
            clean_sheet_count=0, home_clean_sheets=0, away_clean_sheets=0,
            highest_attendance_home=0, highest_attendance_away=0,
            highest_attendance_home_year=None, highest_attendance_away_year=None,
            average_attendance_home=None, average_attendance_away=None,
            longest_streak_start_date=None, longest_streak_end_date=None,
            longest_scoring_streak_start_date=None, longest_scoring_streak_end_date=None,
            longest_clean_sheet_streak_start_date=None, longest_clean_sheet_streak_end_date=None,
            longest_winless_streak_start_date=None, longest_winless_streak_end_date=None,
            longest_unbeaten_start_date=None, longest_unbeaten_end_date=None,
            longest_no_clean_sheet_streak_start_date=None, longest_no_clean_sheet_streak_end_date=None,
            top_scorers=[('', '')], home_wins=0, home_draws=0, home_losses=0,
            away_wins=0, away_draws=0, away_losses=0,
            home_matches=0, away_matches=0,
            home_top_scorer=('', 0), away_top_scorer=('', 0),
            seasons=[], opponents=[], leagues=[], places=[], referees=[],
            current_filters={}, column_visibility={}, is_selected_view=True
        )

    conn = get_db_connection()
    try:
        placeholders = ','.join(['?' for _ in ids])
        query = f'SELECT * FROM Mecze WHERE Id IN ({placeholders}) ORDER BY `Full Date` ASC'
        matches = conn.execute(query, ids).fetchall()

        metrics = calculate_metrics(matches)
        top_scorers = get_top_scorers(matches)
        home_wins, home_draws, home_losses, away_wins, away_draws, away_losses = calculate_home_away_stats(matches)
        home_matches, away_matches = calculate_home_away_matches(matches)
        home_top_scorer, away_top_scorer = calculate_top_scorers_by_location(matches)
        column_visibility = check_column_visibility(matches)

        seasons = get_filter_options(conn, 'Sezon', 'DESC')
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
        home_wins=home_wins, home_draws=home_draws, home_losses=home_losses,
        away_wins=away_wins, away_draws=away_draws, away_losses=away_losses,
        home_matches=home_matches, away_matches=away_matches,
        home_top_scorer=home_top_scorer, away_top_scorer=away_top_scorer,
        **metrics,
        seasons=seasons, opponents=opponents, leagues=leagues,
        places=places, referees=referees,
        current_filters={}, column_visibility=column_visibility,
        is_selected_view=True
    )
if __name__ == '__main__':
    app.run(debug=True)
