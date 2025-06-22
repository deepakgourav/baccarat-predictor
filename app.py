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

print(f"--- DATA FILE PATH IS: {DATA_FILE} ---")

PLAYER, BANKER, TIE = 'Player', 'Banker', 'Tie'
VALID_OUTCOMES = {PLAYER, BANKER, TIE}
VALID_CARDS = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
CARD_VALUES = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 0, 'J': 0, 'Q': 0, 'K': 0}
SIMILARITY_THRESHOLD = 0.9

data_lock = threading.Lock()

# --- Core Data Functions ---

def read_data_file():
    """Safely reads the entire data file."""
    with data_lock:
        if not os.path.isfile(DATA_FILE):
            return []
        try:
            with open(DATA_FILE, 'r') as f:
                content = f.read()
                if not content: return []
                return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            app.logger.error(f"ERROR reading data file: {e}")
            return None

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

def get_current_shoe_state(game_data):
    """
    Scans the provided data to find the most recent shoe and determine if it's active.
    Returns (last_shoe_id, is_active, last_start_index)
    """
    last_shoe_id = None
    last_start_index = -1
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}

    for i in range(len(game_data) - 1, -1, -1):
        record = game_data[i]
        if record.get("event") == "SHOE_START":
            last_shoe_id = record['shoe_id']
            last_start_index = i
            break
            
    if last_shoe_id and last_shoe_id not in ended_shoes:
        return last_shoe_id, True, last_start_index
    else:
        return last_shoe_id, False, last_start_index

# --- Helper Functions ---

def fix_hand(hand_str: str) -> str | None:
    if not isinstance(hand_str, str): return None
    parts = [p.strip().upper() for p in hand_str.split('-')]
    if not all(p in VALID_CARDS for p in parts) or len(parts) not in [2, 3]: return None
    return '-'.join(parts)

def baccarat_total(hand_str: str) -> int:
    return sum(CARD_VALUES.get(card, 0) for card in hand_str.split('-')) % 10

def determine_outcome(player_total: int, banker_total: int) -> str:
    if player_total > banker_total: return PLAYER
    if banker_total > player_total: return BANKER
    return TIE

# --- Prediction Logic Functions ---

def calculate_historical_prediction(user_sequence, all_historical_outcomes):
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

def calculate_sequential_prediction(user_sequence):
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

# --- REPLACE THE 'calculate_current_shoe_prediction' FUNCTION WITH THIS ---

def calculate_current_shoe_prediction(user_sequence):
    """
    Looks for similar patterns within the provided sequence by adaptively
    reducing the pattern length until a match is found.
    """
    if len(user_sequence) < 5:  # Need a minimum length to even attempt a pattern search
        return {'error': 'Need at least 5 rounds for this model.'}

    # Try to find a pattern, starting with a length of 7 and going down to 3.
    for pattern_length in range(7, 2, -1):
        # Ensure we have enough history to even look for this pattern length
        if len(user_sequence) < pattern_length * 2:
            continue  # Skip to the next smaller pattern_length

        pattern_to_match = user_sequence[-pattern_length:]
        history = user_sequence[:-pattern_length]

        match_results = []
        for i in range(len(history) - pattern_length + 1):
            historical_slice = history[i:i + pattern_length]
            ratio = SequenceMatcher(None, pattern_to_match, historical_slice).ratio()
            
            # Use a high threshold for longer patterns, slightly looser for shorter ones
            threshold = 0.9 if pattern_length > 4 else 0.8

            if ratio >= threshold:
                next_outcome_index = i + pattern_length
                if next_outcome_index < len(history):
                    next_outcome = history[next_outcome_index]
                    if next_outcome != TIE:
                        match_results.append({'next_outcome': next_outcome})
        
        # If we found any matches with this pattern length, we're done.
        if match_results:
            outcome_counts = {k: [r['next_outcome'] for r in match_results].count(k) for k in (PLAYER, BANKER)}
            total_matches = sum(outcome_counts.values())
            
            if total_matches == 0:
                # We found matches but they all led to a Tie, try a shorter pattern
                continue 
            
            prediction = max(outcome_counts, key=outcome_counts.get)
            confidence = round((outcome_counts[prediction] / total_matches) * 100, 2)
            return {
                'prediction': prediction,
                'confidence': f"{confidence}%",
                'based_on': f"current_shoe_pattern_match ({pattern_length}-round pattern)",
                'matches_found': len(match_results)
            }

    # If the loop finishes without finding any patterns of any length
    return {'error': 'No repeating patterns found in the current shoe.'}

def calculate_best_fit_shoe_prediction(user_sequence, all_past_shoes):
    if len(user_sequence) < 5: return {'error': 'Need at least 5 rounds to find a best-fit shoe.'}
    best_match = {'shoe_id': None, 'ratio': 0.0, 'next_outcome': None}
    for shoe_id, past_shoe_outcomes in all_past_shoes.items():
        if len(past_shoe_outcomes) > len(user_sequence):
            comparison_slice = past_shoe_outcomes[:len(user_sequence)]
            ratio = SequenceMatcher(None, user_sequence, comparison_slice).ratio()
            if ratio > best_match['ratio']:
                next_outcome_in_past_shoe = past_shoe_outcomes[len(user_sequence)]
                if next_outcome_in_past_shoe != TIE:
                    best_match['shoe_id'] = shoe_id; best_match['ratio'] = ratio; best_match['next_outcome'] = next_outcome_in_past_shoe
    if best_match['ratio'] < 0.7: return {'error': f"No similar past shoe found (Best match was only {round(best_match['ratio']*100)}% similar)."}
    prediction = best_match['next_outcome']; confidence = round(best_match['ratio'] * 100, 2)
    return {'prediction': prediction, 'confidence': f"{confidence}% (similarity)", 'based_on': f"best_fit_shoe_match (shoe {best_match['shoe_id']})"}

# ---------- Flask Routes ----------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/start_new_shoe', methods=['POST'])
def start_new_shoe():
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500
    last_shoe_id, is_active, _ = get_current_shoe_state(game_data)
    if is_active:
        game_data.append({"event": "SHOE_END", "shoe_id": last_shoe_id})
    all_shoe_numbers = {0}
    for record in game_data:
        if 'shoe_id' in record and record.get('shoe_id'):
            try:
                num = int(re.search(r'\d+', record['shoe_id']).group())
                all_shoe_numbers.add(num)
            except (AttributeError, ValueError): continue
    next_shoe_number = max(all_shoe_numbers) + 1
    new_shoe_id = f"shoe_{next_shoe_number}"
    game_data.append({"event": "SHOE_START", "shoe_id": new_shoe_id})
    if not write_data_file(game_data): return jsonify({'error': 'Failed to save new shoe data.'}), 500
    return jsonify({'message': f'Successfully started {new_shoe_id}.'}), 201

@app.route('/add_game', methods=['POST'])
def add_game():
    req_data = request.get_json()
    if not req_data: return jsonify({'error': 'Invalid JSON payload'}), 400
    player_hand = fix_hand(req_data.get('player_hand'))
    banker_hand = fix_hand(req_data.get('banker_hand'))
    outcome = req_data.get('outcome')
    if not all([player_hand, banker_hand, outcome]): return jsonify({'error': 'All fields are required.'}), 400
    if determine_outcome(baccarat_total(player_hand), baccarat_total(banker_hand)) != outcome: return jsonify({'error': "Outcome does not match card totals."}), 400
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500
    current_shoe_id, is_active, shoe_start_index = get_current_shoe_state(game_data)
    if not is_active: return jsonify({'error': 'No active shoe. Please start a new shoe first.'}), 400
    round_count = 1 + sum(1 for rec in game_data[shoe_start_index:] if rec.get('shoe_id') == current_shoe_id and 'outcome' in rec)
    new_game = {'player_hand': player_hand, 'banker_hand': banker_hand, 'outcome': outcome, 'shoe_id': current_shoe_id, 'round': round_count}
    game_data.append(new_game)
    if not write_data_file(game_data): return jsonify({'error': 'Failed to save data.'}), 500
    return jsonify({'message': f'Game added to {current_shoe_id}, round {round_count}.'}), 201

@app.route('/predict_sequence', methods=['POST'])
def predict_sequence():
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500
    
    user_sequence = request.get_json().get('outcomes', [])
    if not isinstance(user_sequence, list) or len(user_sequence) == 0: 
        return jsonify({'error': 'Please provide a sequence.'}), 400

    all_outcomes = [g['outcome'] for g in game_data if 'outcome' in g]
    
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}
    current_shoe_id = None
    for record in reversed(game_data):
        if record.get("event") == "SHOE_START" and record.get('shoe_id') and record['shoe_id'] not in ended_shoes:
            current_shoe_id = record['shoe_id']
            break
    
    all_past_shoes = {}
    for record in game_data:
        if 'outcome' in record and record.get('shoe_id') != current_shoe_id:
            shoe_id = record['shoe_id']
            if shoe_id not in all_past_shoes:
                all_past_shoes[shoe_id] = []
            all_past_shoes[shoe_id].append(record['outcome'])

    return jsonify({
        'best_fit_shoe_prediction': calculate_best_fit_shoe_prediction(user_sequence, all_past_shoes),
        'current_shoe_prediction': calculate_current_shoe_prediction(user_sequence),
        'historical_prediction': calculate_historical_prediction(user_sequence, all_outcomes),
        'sequential_prediction': calculate_sequential_prediction(user_sequence)
    })

@app.route('/end_current_shoe', methods=['POST'])
def end_current_shoe():
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500
    last_shoe_id, is_active, _ = get_current_shoe_state(game_data)
    if not is_active: return jsonify({'error': 'No active shoe to end.'}), 400
    game_data.append({"event": "SHOE_END", "shoe_id": last_shoe_id})
    if not write_data_file(game_data): return jsonify({'error': 'Failed to save shoe end data.'}), 500
    return jsonify({'message': f'Successfully ended {last_shoe_id}.'}), 200

# ---------- App Execution ----------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
