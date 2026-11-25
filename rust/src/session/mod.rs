pub mod driver;
pub mod replay;
pub mod reporting;
pub mod supervisor;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum SessionError {
    #[error("configuration-boundary")]
    ConfigurationBoundary,
    #[error("monotonic-clock-regressed")]
    ClockRegressed,
    #[error("source-drain-timeout")]
    SourceDrainTimeout,
    #[error("source-drain-native-failed")]
    SourceDrainNativeFailed,
    #[error("phase-timeout")]
    PhaseTimeout,
    #[error("initialization-timeout")]
    InitializationTimeout,
    #[error("native-session-closed")]
    NativeSessionClosed,
    #[error("trusted-peer-missing")]
    TrustedPeerMissing,
    #[error("local-account-id-missing")]
    LocalAccountIdMissing,
    #[error("unexpected-challenge-message")]
    UnexpectedChallengeMessage,
    #[error("challenge-peer-mismatch")]
    ChallengePeerMismatch,
    #[error("challenge-context-mismatch")]
    ChallengeContextMismatch,
    #[error("challenge-auth-changed")]
    ChallengeAuthChanged,
    #[error("unexpected-connection-reliability")]
    UnexpectedConnectionReliability,
    #[error("unexpected-protocol-phase")]
    UnexpectedProtocolPhase,
    #[error("observer-cvar-query-rate-budget")]
    CvarQueryRateBudget,
    #[error("event-subscription-id")]
    EventSubscriptionId,
    #[error("new-before-serverinfo")]
    NewBeforeServerInfo,
    #[error("serverinfo-missing")]
    ServerInfoMissing,
    #[error("spawn-before-parser-initialization")]
    SpawnBeforeParserInit,
    #[error("full-before-spawn-acknowledgement")]
    FullBeforeSpawnAck,
    #[error("world-reinitialization-required: {0}")]
    WorldReinitializationRequired(String),
    #[error("output-closed")]
    OutputClosed,
    #[error("output-record-budget")]
    OutputRecordBudget,
    #[error("output-backpressure")]
    OutputBackpressure,
    #[error("native-error: {0}")]
    Native(String),
    #[error("wire-error: {0}")]
    Wire(#[from] crate::wire::bits::WireError),
    #[error("protocol-error: {0}")]
    Protocol(String),
}
