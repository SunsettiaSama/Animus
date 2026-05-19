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
    INGEST_TURN = "ingest_turn"
    RECALL = "recall"
    SEARCH = "search"
    RUMINATE = "ruminate"
    WANDER = "wander"
    HEARTBEAT_RUMINATE = "heartbeat_ruminate"
    INGEST_EXPERIENCE = "ingest_experience"
    FLUSH = "flush"


class PersonaAction:
    EVOLVE = "evolve"
    CLEAR_DRIFT = "clear_drift"
    EVOLVE_SELF_CONCEPT = "evolve_self_concept"
    GET_SNAPSHOT = "get_snapshot"
    RECORD_INTERACTION = "record_interaction"
