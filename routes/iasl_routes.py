from flask import Blueprint, request, jsonify, current_app

iasl_bp = Blueprint('iasl', __name__, url_prefix='/api/iasl')

@iasl_bp.route('/status', methods=['GET'])
def get_status():
    """Retrieve current state, configuration, and latest decision of IASL."""
    controller = current_app.extensions.get('iasl_controller')
    if not controller:
        return jsonify({"success": False, "message": "IASL controller not initialized."}), 500
    return jsonify({"success": True, "status": controller.get_status()}), 200

@iasl_bp.route('/metrics', methods=['GET'])
def get_metrics():
    """Instantaneous metric snapshot with normalized pressure components."""
    collector = current_app.extensions.get('metrics_collector')
    if not collector:
        return jsonify({"success": False, "message": "Metrics collector not initialized."}), 500
    return jsonify({"success": True, "metrics": collector.collect()}), 200

@iasl_bp.route('/history', methods=['GET'])
def get_history():
    """Retrieve chronological decision history and telemetry timeline."""
    history = current_app.extensions.get('controller_history')
    limit = int(request.args.get('limit', 30))
    if not history:
        return jsonify({"success": False, "message": "Controller history not initialized."}), 500
    
    return jsonify({
        "success": True,
        "decisions": history.get_recent_decisions(limit=limit),
        "metrics_timeline": history.get_metrics_timeline(limit=limit)
    }), 200

@iasl_bp.route('/evaluate', methods=['POST'])
def trigger_evaluation():
    """
    Manually triggers an IASL evaluation cycle.
    Accepts optional synthetic metrics override for demonstration/testing.
    """
    controller = current_app.extensions.get('iasl_controller')
    if not controller:
        return jsonify({"success": False, "message": "IASL controller not initialized."}), 500

    data = request.get_json() or {}
    metrics_override = data.get('metrics_override')
    decision_result = controller.evaluate_system(metrics_override=metrics_override)
    
    return jsonify({"success": True, "result": decision_result}), 200
