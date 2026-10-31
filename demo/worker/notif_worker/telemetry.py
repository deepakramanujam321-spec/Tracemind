"""OpenTelemetry setup: traces + logs over OTLP/HTTP protobuf.

Endpoint comes from OTEL_EXPORTER_OTLP_ENDPOINT (SDK appends /v1/traces and /v1/logs).
Tests pass in-memory exporters instead.
"""
import logging
import os

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor


def setup_telemetry(service_name, span_exporter=None, log_exporter=None):
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
        "deployment.environment": os.getenv("DEPLOYMENT_ENVIRONMENT", "demo"),
    })
    in_test = span_exporter is not None
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(
        SimpleSpanProcessor(span_exporter) if in_test else BatchSpanProcessor(OTLPSpanExporter())
    )
    trace.set_tracer_provider(tp)

    lp = LoggerProvider(resource=resource)
    if log_exporter is not None:
        lp.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
    elif not in_test:
        lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(lp)
    handler = LoggingHandler(level=logging.INFO, logger_provider=lp)
    # never export the SDK's own logs (avoids recursion on exporter errors)
    handler.addFilter(lambda r: not r.name.startswith("opentelemetry"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return tp, lp
