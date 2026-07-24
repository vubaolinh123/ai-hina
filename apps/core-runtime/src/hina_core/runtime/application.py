from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .durable import DurableStore
from .error_log import JsonlErrorLogger
from .observability import MetricRegistry
from .primitives import PrimitiveError, RuntimeErrorCode
from .transport import ControlPlaneServer, TransportConfig


ROOT = Path(__file__).resolve().parents[5]


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    database: Path
    error_log: Path
    static_dir: Path | None = None
    audit_log: Path | None = None
    safety_manifest: Path | None = None
    persona_spec: Path | None = None


class HinaRuntimeApplication:
    """Owns the persistent resources that make up the local M01 application."""

    def __init__(
        self,
        config: TransportConfig,
        paths: RuntimePaths,
        *,
        build_commit: str = "development",
        model_gateway: Any | None = None,
        speech_service: Any | None = None,
    ) -> None:
        self.config = config
        self.paths = paths
        self.build_commit = build_commit
        self.metrics = MetricRegistry()
        self.error_logger = JsonlErrorLogger(
            paths.error_log.resolve(),
            build_commit=build_commit,
        )
        self.store: DurableStore | None = None
        self.server: ControlPlaneServer | None = None
        self.safety_policy: Any | None = None
        self.model_gateway: Any | None = model_gateway
        self.conversation: Any | None = None
        self.speech_service: Any | None = speech_service

    @property
    def address(self) -> tuple[str, int]:
        if self.server is None:
            raise RuntimeError("Hina runtime application is not running")
        return self.server.address

    async def __aenter__(self) -> HinaRuntimeApplication:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    async def start(self) -> tuple[str, int]:
        if self.server is not None:
            return self.server.address
        safety_policy = None
        if self.paths.audit_log is not None or self.paths.safety_manifest is not None:
            if self.paths.audit_log is None or self.paths.safety_manifest is None:
                raise ValueError("audit_log and safety_manifest must be configured together")
            from hina_safety import AuditTrail, CapabilityManifest, SafetyPolicyService

            manifest = CapabilityManifest.load(self.paths.safety_manifest.resolve())
            audit = AuditTrail(
                self.paths.audit_log.resolve(),
                build_commit=self.build_commit,
            )
            safety_policy = SafetyPolicyService(manifest, audit)
        store = DurableStore(self.paths.database.resolve())
        conversation = None
        speech_service = self.speech_service
        try:
            model_gateway = self.model_gateway
            if model_gateway is None:
                from hina_text_brain import (
                    LocalResourceScheduler,
                    ModelGateway,
                    ModelGatewayConfig,
                    NvidiaSmiTelemetry,
                )

                model_gateway = ModelGateway(
                    ModelGatewayConfig.from_env(),
                    LocalResourceScheduler(NvidiaSmiTelemetry()),
                )
            if self.paths.persona_spec is not None:
                if safety_policy is None:
                    raise ValueError("persona_spec requires safety policy configuration")
                from hina_text_brain import ConversationService, PersonaSpec

                conversation = ConversationService(
                    model_gateway,
                    safety_policy,
                    PersonaSpec.load(self.paths.persona_spec.resolve()),
                    on_error=self._log_conversation_error,
                )
            if speech_service is None:
                from hina_speech import FasterWhisperProvider, SpeechConfig, SpeechInputService

                speech_config = SpeechConfig.from_env(root=ROOT)
                scheduler = getattr(model_gateway, "scheduler", None)
                gpu_lease_factory = None
                if scheduler is not None:
                    from hina_text_brain import LocalResourceRequest

                    async def acquire_stt_lease(unload: Any) -> Any:
                        return await scheduler.acquire(
                            LocalResourceRequest(
                                owner="stt.whisper",
                                vram_mib=speech_config.model_vram_mib,
                                ram_mib=speech_config.model_ram_mib,
                                priority=90,
                                ttl_seconds=speech_config.request_timeout_seconds + 10,
                                preemptible=False,
                            ),
                            wait_timeout_seconds=3,
                            on_preempt=unload,
                        )

                    gpu_lease_factory = acquire_stt_lease
                speech_service = SpeechInputService(
                    speech_config,
                    FasterWhisperProvider(
                        speech_config,
                        gpu_lease_factory=gpu_lease_factory,
                    ),
                    on_error=self._log_speech_error,
                )
            server = ControlPlaneServer(
                self.config,
                durable_store=store,
                error_logger=self.error_logger,
                metrics=self.metrics,
                static_dir=self.paths.static_dir,
                safety_policy=safety_policy,
                model_gateway=model_gateway,
                conversation_service=conversation,
                speech_service=speech_service,
                build_commit=self.build_commit,
            )
            await server.start()
        except Exception:
            if conversation is not None:
                await conversation.close()
            if speech_service is not None:
                await speech_service.close()
            store.close()
            raise
        self.store = store
        self.server = server
        self.safety_policy = safety_policy
        self.model_gateway = model_gateway
        self.conversation = conversation
        self.speech_service = speech_service
        self.metrics.set_gauge(
            "hina_runtime_ready",
            1,
            labels={"component": "core_runtime"},
        )
        return server.address

    async def serve_forever(self) -> None:
        if self.server is None:
            await self.start()
        assert self.server is not None
        await self.server.serve_forever()

    async def stop(self) -> None:
        server = self.server
        store = self.store
        conversation = self.conversation
        speech_service = self.speech_service
        self.server = None
        self.store = None
        self.safety_policy = None
        self.conversation = None
        self.speech_service = None
        if server is not None:
            await server.stop()
        if conversation is not None:
            await conversation.close()
        if speech_service is not None:
            await speech_service.close()
        if store is not None:
            store.close()

    def _log_conversation_error(self, record: dict[str, str]) -> None:
        self.error_logger.log_error(
            PrimitiveError(
                RuntimeErrorCode.OPERATION_FAILED,
                record["errorCode"],
            ),
            component="text_brain.conversation",
            operation="turn",
            correlation_id=record["correlationId"],
            context={
                "turnId": record["turnId"],
                "sessionId": record["sessionId"],
                "inputHash": record["inputHash"],
            },
        )

    def _log_speech_error(self, record: dict[str, str]) -> None:
        self.error_logger.log_error(
            PrimitiveError(record["errorCode"], "speech input operation failed"),  # type: ignore[arg-type]
            component="speech.input",
            operation="transcribe",
            correlation_id=record["correlationId"],
            session_id=record["sessionId"] or None,
            context={
                "audioBytes": record["audioBytes"],
                "durationMilliseconds": record["durationMilliseconds"],
                "rawAudioRetained": False,
            },
        )
