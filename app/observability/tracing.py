"""OpenTelemetry tracing setup."""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)


def setup_tracing(service_name: str, endpoint: str, enabled: bool = True) -> None:
    """Configure OpenTelemetry tracing."""
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if enabled:
        try:
            otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info("OTLP tracing exporter configured: %s", endpoint)
        except Exception as exc:
            logger.warning("Failed to configure OTLP exporter: %s – falling back to console", exc)
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    logger.info("Tracing initialised for service '%s'", service_name)


def get_tracer(name: str = "ocr-service") -> trace.Tracer:
    return trace.get_tracer(name)
