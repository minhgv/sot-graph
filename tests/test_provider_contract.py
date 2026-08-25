"""Tests for the provider contract (P0 — EvidenceEnvelope vocabulary)."""

from sot_graph.provider_contract import (
    Assertion,
    Capability,
    EvidenceEnvelope,
    IntegrationMode,
    ProviderIdentity,
    SnapshotBinding,
    Subject,
    VerificationResult,
)


def _envelope(**overrides):
    kwargs: dict = dict(
        provider=ProviderIdentity(
            name="gitnexus",
            version="1.2.3",
            mode=IntegrationMode.FEDERATED_CLI,
            capability=Capability.IMPACT,
        ),
        snapshot=SnapshotBinding(
            repository_root="/repo",
            commit_sha="abc123",
            worktree_fingerprint="sha256:ff00",
            manifest_digest="sha256:aa11",
            dirty=True,
            snapshot_id="snap_1",
        ),
        subject=Subject(
            kind="function",
            qualified_name="app.process_order",
            path="src/app/service.py",
            start_line=42,
            end_line=71,
            content_hash="sha256:bb22",
        ),
        assertion=Assertion(relation="CALLS", target="app.payment.charge", provider_confidence=0.92),
        verification=VerificationResult(
            status="SUPPORTED",
            source_span_verified=True,
            snapshot_verified=True,
        ),
    )
    kwargs.update(overrides)
    return EvidenceEnvelope(**kwargs)


class TestEvidenceEnvelope:
    def test_valid_envelope_has_no_problems(self):
        assert _envelope().validate() == []

    def test_unbound_snapshot_cannot_be_supported(self):
        env = _envelope(
            snapshot=SnapshotBinding("/repo", None, None, None, False, snapshot_id=None),
            verification=VerificationResult(status="SUPPORTED", source_span_verified=True, snapshot_verified=False),
        )
        assert any("UNBOUND" in p for p in env.validate())

    def test_federated_cli_requires_detected_version(self):
        env = _envelope(provider=ProviderIdentity("gitnexus", None, IntegrationMode.FEDERATED_CLI, Capability.IMPACT))
        assert any("version" in p for p in env.validate())

    def test_confidence_out_of_range_rejected(self):
        assert _envelope(assertion=Assertion("CALLS", "t", 1.5)).validate()

    def test_absolute_subject_path_rejected(self):
        assert _envelope(subject=Subject("function", "f", "/abs/path.py", 1, 2, None)).validate()

    def test_to_dict_matches_guide_shape(self):
        d = _envelope().to_dict()
        assert d["schema_version"] == 1
        assert set(d) == {"schema_version", "provider", "snapshot", "subject", "assertion", "verification"}
        assert d["provider"]["mode"] == "federated-cli"
        assert d["provider"]["capability"] == "impact"
        assert d["snapshot"]["commit"] == "abc123"
        assert d["verification"]["status"] == "SUPPORTED"
