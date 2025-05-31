from flask import Flask, request, jsonify, render_template
from difflib import SequenceMatcher
import json
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'data', 'game_data.json')

# ---------- Utilities ----------
def create_initial_data():
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w') as f:
            json.dump([], f, indent=2)

def fix_hand(hand_str):
    valid_cards = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
    hand_str = str(hand_str).replace('-', '')
    cards = []
    i = 0
    while i < len(hand_str):
        if hand_str[i] == '1' and i+1 < len(hand_str) and hand_str[i+1] == '0':
            cards.append('10')
            i += 2
        else:
            cards.append(hand_str[i])
            i += 1
    return '-'.join(card for card in cards if card in valid_cards)

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except:
        return []

def save_data(data):
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except:
        return False

# ---------- Baccarat Logic ----------
card_values = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5,
               '6': 6, '7': 7, '8': 8, '9': 9,
               '10': 0, 'J': 0, 'Q': 0, 'K': 0}

def baccarat_total(hand_str):
    try:
        cards = hand_str.split('-')
        return sum(card_values.get(card, 0) for card in cards) % 10
    except:
        return 0

def is_natural(total):
    return total in [8, 9]

def early_end(player_total, banker_total):
    if is_natural(player_total) or is_natural(banker_total):
        return True
    if {player_total, banker_total} == {6, 7}:
        return True
    if player_total == banker_total and player_total in [6, 7, 8, 9]:
        return True
    return False

def determine_outcome(player_total, banker_total):
    if player_total > banker_total:
        return 'Player'
    elif banker_total > player_total:
        return 'Banker'
    else:
        return 'Tie'

# ---------- Routes ----------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/debug')
def debug_template():
    return jsonify({
        "template_dir": os.path.abspath("templates"),
        "index_exists": os.path.exists("templates/index.html")
    })

@app.route('/add_game', methods=['POST'])
def add_game():
    try:
        data = request.get_json()
        player_hand = fix_hand(data.get('player_hand', ''))
        banker_hand = fix_hand(data.get('banker_hand', ''))
        outcome = data.get('outcome', '')

        if not all([player_hand, banker_hand, outcome]):
            return jsonify({'error': 'All fields are required'}), 400

        if outcome not in ['Player', 'Banker', 'Tie']:
            return jsonify({'error': 'Invalid outcome'}), 400

        player_total = baccarat_total(player_hand)
        banker_total = baccarat_total(banker_hand)
        predicted = determine_outcome(player_total, banker_total)

        if predicted != outcome:
            return jsonify({'error': f"Outcome does not match card totals. Calculated: {predicted}"}), 400

        games = load_data()
        games.append({
            'player_hand': player_hand,
            'banker_hand': banker_hand,
            'outcome': outcome
        })

        if not save_data(games):
            return jsonify({'error': 'Failed to save data'}), 500

        return jsonify({'message': 'Game added successfully'}), 201
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

@app.route('/predict_sequence', methods=['POST'])
def predict_sequence():
    try:
        data = request.get_json()
        user_sequence = data.get('outcomes', [])

        # ✅ Allow "Player", "Banker", "Tie" in input sequence
        if len(user_sequence) != 10 or any(o not in ["Player", "Banker", "Tie"] for o in user_sequence):
            return jsonify({'error': 'Please provide exactly 10 valid outcomes: "Player", "Banker", or "Tie"'}), 400

        historical_data = load_data()
        all_outcomes = [g['outcome'] for g in historical_data]

        match_results = []

        for i in range(len(all_outcomes) - 10):
            window = all_outcomes[i:i+10]
            next_outcome = all_outcomes[i+10] if i + 10 < len(all_outcomes) else None

            if not next_outcome or next_outcome not in ['Player', 'Banker']:
                continue  # skip predicting "Tie" as next outcome

            exact_match = user_sequence == window
            fuzzy_match_ratio = SequenceMatcher(None, user_sequence, window).ratio()

            if exact_match or fuzzy_match_ratio >= 0.8:
                match_results.append({
                    'start_index': i,
                    'matched_sequence': window,
                    'next_outcome': next_outcome,
                    'match_type': 'exact' if exact_match else 'fuzzy',
                    'similarity': round(fuzzy_match_ratio * 100, 2)
                })

        if match_results:
            outcome_counts = {'Player': 0, 'Banker': 0}
            for match in match_results:
                outcome_counts[match['next_outcome']] += 1

            total = outcome_counts['Player'] + outcome_counts['Banker']
            predicted = max(outcome_counts, key=outcome_counts.get)
            confidence = round((outcome_counts[predicted] / total) * 100, 2)

            return jsonify({
                'prediction': predicted,
                'confidence': f"{confidence}%",
                'based_on': 'pattern_match',
                'matches_found': len(match_results),
                'match_details': match_results[:5]
            })
        else:
            fallback_counts = {'Player': user_sequence.count('Player'), 'Banker': user_sequence.count('Banker')}
            fallback_pred = max(fallback_counts, key=fallback_counts.get)
            fallback_conf = round((fallback_counts[fallback_pred] / (fallback_counts['Player'] + fallback_counts['Banker'])) * 100, 2)

            return jsonify({
                'prediction': fallback_pred,
                'confidence': f"{fallback_conf}%",
                'based_on': 'fallback_logic',
                'reason': 'no matching pattern found in historical data'
            })
    except Exception as e:
        return jsonify({'error': 'Prediction failed', 'details': str(e)}), 500

# ---------- Run App ----------
if __name__ == '__main__':
    create_initial_data()
    app.run(host='0.0.0.0', port=3000, debug=True)
