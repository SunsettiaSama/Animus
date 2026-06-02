class LifeAction:
    FABRICATE = "fabricate"
    RECORD_TURN = "record_turn"
    ADD_LANDMARK = "add_landmark"
    LOAD_PROFILE = "load_profile"
    STATUS = "status"
    PLAN_LANDMARK = "plan_landmark"
    COMPOSE_LANDMARK = "compose_landmark"
    COUNT_LANDMARKS_SINCE = "count_landmarks_since"
    TRIGGER_LANDMARKS = "trigger_landmarks"
    TICK_SURPRISE = "tick_surprise"
    RECORD_SCHEDULER_DIGEST = "record_scheduler_digest"
    RECENT_CHRONICLE = "recent_chronicle"
    HOT_STORAGE = "hot_storage"


class MemoryAction:
    RECALL = "recall"
    SEARCH = "search"
    NARRATIVE_CONTINUITY = "narrative_continuity"
    WANDER = "wander"
    FORGET_SCAN = "forget_scan"
    SLEEP = "sleep"
    FLUSH = "flush"
    FETCH_PERSONA_CLUSTER = "fetch_persona_cluster"
    LIST_DRIFT_UNITS = "list_drift_units"
    GET_ACTIVATION_SNAPSHOT = "get_activation_snapshot"
    GET_POINT_EMERGENCE = "get_point_emergence"


class PersonaAction:
    RESET_SELF_CONCEPT = "reset_self_concept"
    GET_SNAPSHOT = "get_snapshot"
    PORTRAIT_REVISION = "portrait_revision"
    PORTRAIT_FOR_NARRATIVE = "portrait_for_narrative"
    RELOAD_PROFILE = "reload_profile"
    REBUILD_PROFILE = "rebuild_profile"
    GET_BUFFER = "get_buffer"
    RUN_MONTHLY_DRIFT = "run_monthly_drift"
    ENSURE_DISTILL = "ensure_distill"
    GET_DISTILL = "get_distill"


from agent.soul.speak.io.actions import SpeakAction  # noqa: E402
