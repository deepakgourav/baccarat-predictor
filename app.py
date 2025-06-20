# --- START OF FILE app.py (STATE-SAFE FINAL VERSION) ---

from flask import Flask, request, jsonify, render_template
from difflib import SequenceMatcher
import json
import os
import threading
import re

# ---------- Configuration & Constants ----------
app = Flask(__name__)

# --- SIMPLE & RELIABLE PATH CONFIGURATION ---
# This method ensures that the paths are always relative to where the app.py script itself is located.
# This avoids any issues with the "current working directory".
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DATA_FILE = os.path.join(DATA_DIR, 'game_data.json')
# --- END OF PATH CONFIGURATION ---

# ... (the rest of your app.py code remains the same)
print(f"--- DATA FILE PATH IS: {DATA_FILE} ---")

PLAYER, BANKER, TIE = 'Player', 'Banker', 'Tie'
# ... (rest of constants are the same)
VALID_OUTCOMES = {PLAYER, BANKER, TIE}
VALID_CARDS = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
CARD_VALUES = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 0, 'J': 0, 'Q': 0, 'K': 0}
SIMILARITY_THRESHOLD = 0.8


# --- STATE-SAFE FILE HANDLING ---
# A lock is still used to prevent two requests from writing at the exact same time.
data_lock = threading.Lock()

def read_data_file():
    """Safely reads the entire data file."""
    with data_lock:
        if not os.path.isfile(DATA_FILE):
            return [] # Return empty list if no file
        try:
            with open(DATA_FILE, 'r') as f:
                content = f.read()
                if not content: return []
                return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            app.logger.error(f"ERROR reading data file: {e}")
            return None # Return None on error

def write_data_file(data):
    """Safely writes data to the file."""
    with data_lock:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except IOError as e:
            app.logger.error(f"ERROR writing data file: {e}")
            return False

# ----- All other functions remain the same, we just change the routes -----

def fix_hand(hand_str: str) -> str | None: # ... (no change)
    if not isinstance(hand_str, str): return None
    parts = [p.strip().upper() for p in hand_str.split('-')]
    if not all(p in VALID_CARDS for p in parts) or len(parts) not in [2, 3]: return None
    return '-'.join(parts)
def baccarat_total(hand_str: str) -> int: # ... (no change)
    return sum(CARD_VALUES.get(card, 0) for card in hand_str.split('-')) % 10
def determine_outcome(player_total: int, banker_total: int) -> str: # ... (no change)
    if player_total > banker_total: return PLAYER
    if banker_total > player_total: return BANKER
    return TIE
def calculate_historical_prediction(user_sequence, all_historical_outcomes): # ... (no change)
    seq_len = len(user_sequence)
    if len(all_historical_outcomes) <= seq_len: return {'error': 'Not enough historical data.'}
    match_results = [{'next_outcome': all_historical_outcomes[i + seq_len]} for i in range(len(all_historical_outcomes) - seq_len) if SequenceMatcher(None, user_sequence, all_historical_outcomes[i:i + seq_len]).ratio() >= SIMILARITY_THRESHOLD and all_historical_outcomes[i + seq_len] != TIE]
    if not match_results:
        pb_counts = {k: user_sequence.count(k) for k in (PLAYER, BANKER)}; total = sum(pb_counts.values())
        if total == 0: return {'prediction': 'Banker', 'confidence': "0%", 'based_on': 'fallback_no_data'}
        prediction = max(pb_counts, key=pb_counts.get); confidence = round((pb_counts[prediction] / total) * 100, 2)
        return {'prediction': prediction, 'confidence': f"{confidence}%", 'based_on': 'fallback_logic'}
    outcome_counts = {k: [r['next_outcome'] for r in match_results].count(k) for k in (PLAYER, BANKER)}; total_matches = sum(outcome_counts.values())
    if total_matches == 0: return {'error': 'Matches found, but all lead to a Tie.'}
    prediction = max(outcome_counts, key=outcome_counts.get); confidence = round((outcome_counts[prediction] / total_matches) * 100, 2)
    return {'prediction': prediction, 'confidence': f"{confidence}%", 'based_on': 'pattern_match', 'matches_found': len(match_results)}
def calculate_sequential_prediction(user_sequence): # ... (no change)
    if len(user_sequence) < 2: return {'error': 'Sequence too short for this analysis.'}
    transitions = {PLAYER: {PLAYER: 0, BANKER: 0}, BANKER: {PLAYER: 0, BANKER: 0}}
    for i in range(len(user_sequence) - 1):
        current, next_val = user_sequence[i], user_sequence[i+1]
        if current in transitions and next_val in transitions[current]: transitions[current][next_val] += 1
    last_outcome = user_sequence[-1]
    if last_outcome not in transitions: return {'prediction': 'Banker', 'confidence': '0%', 'based_on': 'sequential_fallback', 'reason': 'Last round was a Tie.'}
    possible_outcomes = transitions[last_outcome]; total_transitions = sum(possible_outcomes.values())
    if total_transitions == 0: return {'prediction': 'Banker', 'confidence': '0%', 'based_on': 'sequential_fallback', 'reason': f'No transitions from "{last_outcome}" found in sequence.'}
    prediction = max(possible_outcomes, key=possible_outcomes.get); confidence = round((possible_outcomes[prediction] / total_transitions) * 100, 2)
    return {'prediction': prediction, 'confidence': f"{confidence}%", 'based_on': 'transition_analysis'}


# ---------- Flask Routes (REWRITTEN TO BE STATE-SAFE) ----------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/start_new_shoe', methods=['POST'])
def start_new_shoe():
    # READ the latest data from the file
    game_data = read_data_file()
    if game_data is None:
        return jsonify({'error': 'Could not read data file.'}), 500

    # Determine state from the fresh data
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}
    last_shoe_id = None
    is_active = False
    for record in reversed(game_data):
        if record.get("event") == "SHOE_START":
            last_shoe_id = record['shoe_id']
            if last_shoe_id not in ended_shoes:
                is_active = True
            break
    
    # LOGIC: If a shoe is active, end it
    if is_active:
        game_data.append({"event": "SHOE_END", "shoe_id": last_shoe_id})

    # LOGIC: Find the highest existing shoe number and add 1
    all_shoe_numbers = {0}
    for record in game_data:
        if 'shoe_id' in record and record.get('shoe_id'):
            try:
                num = int(re.search(r'\d+', record['shoe_id']).group())
                all_shoe_numbers.add(num)
            except (AttributeError, ValueError): continue
    
    next_shoe_number = max(all_shoe_numbers) + 1
    new_shoe_id = f"shoe_{next_shoe_number}"
    
    # MODIFY the data and WRITE it back to the file
    game_data.append({"event": "SHOE_START", "shoe_id": new_shoe_id})
    if not write_data_file(game_data):
        return jsonify({'error': 'Failed to save new shoe data.'}), 500

    return jsonify({'message': f'Successfully started {new_shoe_id}.'}), 201


@app.route('/add_game', methods=['POST'])
def add_game():
    req_data = request.get_json() # Renamed to avoid confusion with file data
    if not req_data: return jsonify({'error': 'Invalid JSON payload'}), 400
    
    # ... (Validation is the same) ...
    player_hand = fix_hand(req_data.get('player_hand'))
    banker_hand = fix_hand(req_data.get('banker_hand'))
    outcome = req_data.get('outcome')
    if not all([player_hand, banker_hand, outcome]): return jsonify({'error': 'All fields are required.'}), 400
    if determine_outcome(baccarat_total(player_hand), baccarat_total(banker_hand)) != outcome: return jsonify({'error': "Outcome does not match card totals."}), 400
    
    # READ the latest data from the file
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500

    # Determine current shoe state from fresh data
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}
    current_shoe_id, shoe_start_index, is_active = None, -1, False
    for i in range(len(game_data) - 1, -1, -1):
        record = game_data[i]
        if record.get("event") == "SHOE_START":
            current_shoe_id = record['shoe_id']
            if current_shoe_id not in ended_shoes:
                is_active = True
                shoe_start_index = i
            break
            
    if not is_active: return jsonify({'error': 'No active shoe. Please start a new shoe first.'}), 400

    # LOGIC: Calculate round number and add game
    round_count = 1 + sum(1 for rec in game_data[shoe_start_index:] if rec.get('shoe_id') == current_shoe_id and 'outcome' in rec)
    new_game = {'player_hand': player_hand, 'banker_hand': banker_hand, 'outcome': outcome, 'shoe_id': current_shoe_id, 'round': round_count}
    
    # MODIFY the data and WRITE it back
    game_data.append(new_game)
    if not write_data_file(game_data):
        return jsonify({'error': 'Failed to save data.'}), 500

    return jsonify({'message': f'Game added to {current_shoe_id}, round {round_count}.'}), 201


@app.route('/predict_sequence', methods=['POST'])
def predict_sequence():
    # This route only reads, so it's fine.
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500
    
    user_sequence = request.get_json().get('outcomes', [])
    if not isinstance(user_sequence, list) or len(user_sequence) < 10: return jsonify({'error': 'Please provide at least 10 valid outcomes.'}), 400

    all_outcomes = [g['outcome'] for g in game_data if 'outcome' in g]
    return jsonify({'historical_prediction': calculate_historical_prediction(user_sequence, all_outcomes), 'sequential_prediction': calculate_sequential_prediction(user_sequence)})
# --- ADD THIS MISSING FUNCTION TO YOUR app.py ---

@app.route('/end_current_shoe', methods=['POST'])
def end_current_shoe():
    # READ the latest data from the file
    game_data = read_data_file()
    if game_data is None:
        return jsonify({'error': 'Could not read data file.'}), 500

    # Determine state from the fresh data
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}
    last_shoe_id = None
    is_active = False
    for record in reversed(game_data):
        if record.get("event") == "SHOE_START":
            last_shoe_id = record['shoe_id']
            if last_shoe_id not in ended_shoes:
                is_active = True
            break
            
    if not is_active:
        return jsonify({'error': 'No active shoe to end.'}), 400
    
    # MODIFY the data and WRITE it back
    game_data.append({"event": "SHOE_END", "shoe_id": last_shoe_id})
    if not write_data_file(game_data):
        return jsonify({'error': 'Failed to save shoe end data.'}), 500

    return jsonify({'message': f'Successfully ended {last_shoe_id}.'}), 200

# --- END OF MISSING FUNCTION ---
# No need for initialize_data() call here anymore
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
