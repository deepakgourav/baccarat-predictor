

# ---------- Configuration & Constants ----------
app = Flask(__name__)

# --- SIMPLE & RELIABLE PATH CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DATA_FILE = os.path.join(DATA_DIR, 'game_data.json')
FEEDBACK_FILE = os.path.join(DATA_DIR, 'feedback_data.json')

print(f"--- DATA FILE PATH IS: {DATA_FILE} ---")
print(f"--- FEEDBACK FILE PATH IS: {FEEDBACK_FILE} ---")

PLAYER, BANKER, TIE = 'Player', 'Banker', 'Tie'
VALID_OUTCOMES = {PLAYER, BANKER, TIE}
VALID_CARDS = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
CARD_VALUES = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 0, 'J': 0, 'Q': 0, 'K': 0}
SIMILARITY_THRESHOLD = 0.9

data_lock = threading.Lock()

# --- Core Data Functions (State-Safe) ---

def read_data_file():
    """Safely reads the entire data file."""
    with data_lock:
        os.makedirs(DATA_DIR, exist_ok=True)
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

def record_feedback(prediction_data, actual_outcome):
    """Records prediction feedback for model improvement."""
    feedback_entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'prediction_data': prediction_data,
        'actual_outcome': actual_outcome,
        'was_correct': prediction_data.get('prediction') == actual_outcome
    }
    
    with data_lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            # Read existing feedback
            if os.path.isfile(FEEDBACK_FILE):
                with open(FEEDBACK_FILE, 'r') as f:
                    feedback_data = json.load(f)
            else:
                feedback_data = []
            
            # Add new feedback
            feedback_data.append(feedback_entry)
            
            # Save back to file
            with open(FEEDBACK_FILE, 'w') as f:
                json.dump(feedback_data, f, indent=2)
            
            return True
        except Exception as e:
            app.logger.error(f"Error saving feedback: {e}")
            return False

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
    if len(user_sequence) >= 3:
        last_three = user_sequence[-3:]
        if last_three[0] == last_three[1] == last_three[2] and last_three[0] != TIE:
            streak_outcome = last_three[0]
            opposite_outcome = BANKER if streak_outcome == PLAYER else PLAYER
            streak_continues, streak_breaks = 0, 0
            for i in range(len(all_historical_outcomes) - 3):
                if all_historical_outcomes[i:i+3] == last_three:
                    next_outcome = all_historical_outcomes[i+3]
                    if next_outcome == streak_outcome: streak_continues += 1
                    elif next_outcome == opposite_outcome: streak_breaks += 1
            total_events = streak_continues + streak_breaks
            if total_events > 5:
                if streak_breaks > streak_continues:
                    prediction, confidence = opposite_outcome, round((streak_breaks / total_events) * 100, 2)
                    return {'prediction': prediction, 'confidence': f"{confidence}%", 'based_on': f"streak_break_analysis (after 3x {streak_outcome})", 'matches_found': total_events}
    
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

def enhanced_calculate_historical_prediction(user_sequence, all_historical_outcomes):
    # First try the original prediction
    original_pred = calculate_historical_prediction(user_sequence, all_historical_outcomes)
    
    # If we have enough data, check feedback
    if len(user_sequence) >= 5:
        try:
            with open(FEEDBACK_FILE, 'r') as f:
                feedback_data = json.load(f)
            
            # Find similar sequences in feedback
            similar_feedback = []
            for fb in feedback_data:
                if 'prediction_data' in fb and 'user_sequence' in fb['prediction_data']:
                    fb_seq = fb['prediction_data']['user_sequence']
                    if len(fb_seq) == len(user_sequence):
                        similarity = SequenceMatcher(None, user_sequence, fb_seq).ratio()
                        if similarity >= 0.8:
                            similar_feedback.append(fb)
            
            # If we have significant feedback, adjust prediction
            if len(similar_feedback) >= 3:
                correct_predictions = sum(1 for fb in similar_feedback if fb['was_correct'])
                accuracy = correct_predictions / len(similar_feedback)
                
                # If accuracy is poor, adjust confidence
                if accuracy < 0.5:
                    original_pred['confidence'] = f"{float(original_pred['confidence'].rstrip('%')) * accuracy:.2f}%"
                    original_pred['based_on'] += " + feedback_adjusted"
        
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            app.logger.error(f"Error reading feedback: {e}")
    
    return original_pred

def calculate_current_shoe_prediction(user_sequence):
    if len(user_sequence) < 3:
        return {'error': 'Need at least 3 rounds for this model.'}

    # Look for longer, repeating patterns
    for pattern_length in range(7, 2, -1):
        if len(user_sequence) >= pattern_length * 2:
            pattern_to_match = user_sequence[-pattern_length:]
            history = user_sequence[:-pattern_length]
            match_results = []
            for i in range(len(history) - pattern_length + 1):
                historical_slice = history[i:i + pattern_length]
                if SequenceMatcher(None, pattern_to_match, historical_slice).ratio() >= 0.95:
                    next_outcome_index = i + pattern_length
                    if next_outcome_index < len(history):
                        next_outcome = history[next_outcome_index]
                        if next_outcome != TIE:
                            match_results.append({'next_outcome': next_outcome})
            
            if match_results:
                outcome_counts = {k: [r['next_outcome'] for r in match_results].count(k) for k in (PLAYER, BANKER)}
                total_matches = sum(outcome_counts.values())
                if total_matches > 0:
                    prediction = max(outcome_counts, key=outcome_counts.get)
                    confidence = round((outcome_counts[prediction] / total_matches) * 100, 2)
                    return {
                        'prediction': prediction,
                        'confidence': f"{confidence}%",
                        'based_on': f"current_shoe_pattern_match ({pattern_length}-round pattern)",
                        'matches_found': len(match_results)
                    }

    # Simple fallback if no complex patterns found
    last_outcome = user_sequence[-1]
    if last_outcome == TIE:
        return {'prediction': 'Banker', 'confidence': "0%", 'based_on': 'shoe_fallback (after tie)'}

    player_wins, banker_wins = 0, 0
    for i in range(len(user_sequence) - 1):
        if user_sequence[i] == last_outcome:
            next_in_seq = user_sequence[i+1]
            if next_in_seq == PLAYER: player_wins += 1
            elif next_in_seq == BANKER: banker_wins += 1
    
    total = player_wins + banker_wins
    if total == 0:
        return {'prediction': 'Banker', 'confidence': "0%", 'based_on': 'shoe_fallback (no transitions found)'}
    
    if player_wins > banker_wins:
        prediction = PLAYER
        confidence = round((player_wins / total) * 100, 2)
    else:
        prediction = BANKER
        confidence = round((banker_wins / total) * 100, 2)

    return {
        'prediction': prediction,
        'confidence': f"{confidence}%",
        'based_on': 'shoe_transition_fallback'
    }

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

def weighted_prediction(user_sequence, all_historical_outcomes, all_past_shoes):
    # Get all three predictions
    historical = enhanced_calculate_historical_prediction(user_sequence, all_historical_outcomes)
    current_shoe = calculate_current_shoe_prediction(user_sequence)
    best_fit = calculate_best_fit_shoe_prediction(user_sequence, all_past_shoes)
    
    predictions = {
        'historical': historical,
        'current_shoe': current_shoe,
        'best_fit': best_fit
    }
    
    # If any prediction has error, exclude it
    valid_preds = {k: v for k, v in predictions.items() if not v.get('error')}
    
    if not valid_preds:
        return {'error': 'No valid predictions available'}
    
    # Calculate weights based on confidence
    weighted_votes = {}
    for pred_type, pred_data in valid_preds.items():
        try:
            confidence = float(pred_data['confidence'].rstrip('%'))
            outcome = pred_data['prediction']
            weighted_votes[outcome] = weighted_votes.get(outcome, 0) + confidence
        except (ValueError, KeyError):
            continue
    
    if not weighted_votes:
        return {'error': 'Could not calculate weighted prediction'}
    
    # Get the outcome with highest weighted votes
    final_prediction = max(weighted_votes.items(), key=lambda x: x[1])
    
    return {
        'prediction': final_prediction[0],
        'confidence': f"{final_prediction[1] / sum(weighted_votes.values()) * 100:.2f}%",
        'based_on': 'weighted_ensemble',
        'component_predictions': predictions
    }

# ---------- Flask Routes ----------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/start_new_shoe', methods=['POST'])
def start_new_shoe():
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}
    last_shoe_id, is_active = None, False
    for record in reversed(game_data):
        if record.get("event") == "SHOE_START":
            last_shoe_id = record.get('shoe_id')
            if last_shoe_id not in ended_shoes: is_active = True
            break
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
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}
    current_shoe_id, shoe_start_index, is_active = None, -1, False
    for i, record in enumerate(reversed(game_data)):
        if record.get("event") == "SHOE_START":
            current_shoe_id = record.get('shoe_id')
            if current_shoe_id not in ended_shoes:
                is_active = True
                shoe_start_index = len(game_data) - 1 - i
            break
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
            if shoe_id not in all_past_shoes: all_past_shoes[shoe_id] = []
            all_past_shoes[shoe_id].append(record['outcome'])
    return jsonify({
        'best_fit_shoe_prediction': calculate_best_fit_shoe_prediction(user_sequence, all_past_shoes),
        'current_shoe_prediction': calculate_current_shoe_prediction(user_sequence),
        'historical_prediction': enhanced_calculate_historical_prediction(user_sequence, all_outcomes),
        'weighted_prediction': weighted_prediction(user_sequence, all_outcomes, all_past_shoes)
    })

@app.route('/provide_feedback', methods=['POST'])
def provide_feedback():
    req_data = request.get_json()
    if not req_data or 'prediction_data' not in req_data or 'actual_outcome' not in req_data:
        return jsonify({'error': 'Prediction data and actual outcome required'}), 400
    
    if record_feedback(req_data['prediction_data'], req_data['actual_outcome']):
        return jsonify({'message': 'Feedback recorded successfully'}), 200
    else:
        return jsonify({'error': 'Failed to record feedback'}), 500

@app.route('/end_current_shoe', methods=['POST'])
def end_current_shoe():
    game_data = read_data_file()
    if game_data is None: return jsonify({'error': 'Could not read data file.'}), 500
    ended_shoes = {rec['shoe_id'] for rec in game_data if rec.get('event') == 'SHOE_END'}
    last_shoe_id, is_active = None, False
    for record in reversed(game_data):
        if record.get("event") == "SHOE_START":
            last_shoe_id = record.get('shoe_id')
            if last_shoe_id not in ended_shoes: is_active = True
            break
    if not is_active: return jsonify({'error': 'No active shoe to end.'}), 400
    game_data.append({"event": "SHOE_END", "shoe_id": last_shoe_id})
    if not write_data_file(game_data): return jsonify({'error': 'Failed to save shoe end data.'}), 500
    return jsonify({'message': f'Successfully ended {last_shoe_id}.'}), 200

# ---------- App Execution ----------

