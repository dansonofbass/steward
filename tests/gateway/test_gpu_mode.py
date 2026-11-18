"""The gateway's start-up checks (PR 13b, D5, D7, D9): a GPU image's vendor license accepted first and a plain line when
it sees no GPU (images set STEWARD_GATEWAY_GPU; a gateway without it skips both), and one gateway per name for every
gateway in compose mode, the CPU image included."""
import pytest
from typer.testing import CliRunner

from steward_gateway import cli, gpu, serving
from tests.gateway.license_values import LICENSE_VALUES

MISSING_NVIDIA = ("This gateway image includes NVIDIA's CUDA libraries, which come under NVIDIA's own licenses. Read "
                  "them (docs/guides/gpu.md, \"Licenses\"), then set STEWARD_GPU_LICENSE_ACCEPTED=nvidia in .env and "
                  "start again.")
MISSING_AMD = ("This gateway image includes AMD's ROCm libraries, which come under AMD's own licenses. Read them "
               "(docs/guides/gpu.md, \"Licenses\"), then set STEWARD_GPU_LICENSE_ACCEPTED=amd in .env and start again.")


def wrong(got, vendor, name):
    return (f'STEWARD_GPU_LICENSE_ACCEPTED says "{got}", but this gateway image is for {name}. Read {name}\'s licenses '
            f'(docs/guides/gpu.md, "Licenses"), then set STEWARD_GPU_LICENSE_ACCEPTED={vendor}.')


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("STEWARD_GATEWAY_GPU", "STEWARD_GPU_LICENSE_ACCEPTED"):
        monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize("image, accepted, want", [
    ("nvidia", None, MISSING_NVIDIA), ("nvidia", "", MISSING_NVIDIA), ("amd", None, MISSING_AMD),
    ("nvidia", "amd", wrong("amd", "nvidia", "NVIDIA")), ("amd", "nvidia", wrong("nvidia", "amd", "AMD")),
    ("nvidia", "yes", wrong("yes", "nvidia", "NVIDIA")), ("nvidia", " NVIDIA ", None), ("amd", "amd", None),
    ("intel", "intel", "STEWARD_GATEWAY_GPU must be nvidia or amd."),
    ("", "nvidia", "STEWARD_GATEWAY_GPU must be nvidia or amd.")])        # present but empty: not a way past the gate
def test_a_gpu_image_starts_only_with_its_vendors_license(image, accepted, want):
    env = {"STEWARD_GATEWAY_GPU": image} | ({} if accepted is None else {"STEWARD_GPU_LICENSE_ACCEPTED": accepted})
    assert gpu.license_problem(env) == want
    assert gpu.license_problem({}) is None                      # no GPU image: nothing to accept


@pytest.mark.parametrize("value, vendor, accepted", LICENSE_VALUES)
def test_the_start_up_gate_follows_the_same_rule_as_the_build_gate(value, vendor, accepted):
    """tests/test_gateway_image.py runs the Dockerfiles' RUN check on this same table."""
    problem = gpu.license_problem({"STEWARD_GATEWAY_GPU": vendor, "STEWARD_GPU_LICENSE_ACCEPTED": value})
    assert (problem is None) is accepted


def test_serve_refuses_before_reading_any_config(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: pytest.fail("config read before the license gate"))
    r = CliRunner().invoke(cli.app, ["serve"], env={"STEWARD_GATEWAY_GPU": "nvidia"})
    assert r.exit_code == 1 and r.output.strip() == MISSING_NVIDIA


def _compose(monkeypatch, gw_cfg, tmp_path):
    from dataclasses import replace
    from steward_gateway import config
    marker = tmp_path / ".dockerenv"
    marker.touch()
    monkeypatch.setattr(config, "CONTAINER_MARKERS", (marker,))
    monkeypatch.setattr(cli, "load_config", lambda: replace(gw_cfg, network="compose", host="0.0.0.0",
                                                            ollama_url="http://ollama:11434"))


def _answers(*ips):
    return lambda host, port, *a, **k: [(10 if ":" in ip else 2, 1, 6, "", (ip, port)) for ip in ips]


@pytest.mark.parametrize("image", [None, "nvidia", "amd"], ids=["cpu-image", "nvidia-image", "amd-image"])
def test_two_gateways_under_one_name_refuse_to_serve(monkeypatch, gw_cfg, tmp_path, image):
    """The CPU image checks too: if a GPU gateway starts first and the CPU one second, the CPU one must stop."""
    _compose(monkeypatch, gw_cfg, tmp_path)
    monkeypatch.setattr("steward_gateway.cli.api_key", lambda cfg: None)
    monkeypatch.setattr("steward_gateway.accelerator.available", lambda: "cuda")
    ran = []
    monkeypatch.setattr(serving, "run", lambda cfg, app: ran.append(cfg))
    env = {} if image is None else {"STEWARD_GATEWAY_GPU": image, "STEWARD_GPU_LICENSE_ACCEPTED": image}
    monkeypatch.setattr(gpu.socket, "getaddrinfo", _answers("172.20.0.3", "172.20.0.4"))
    r = CliRunner().invoke(cli.app, ["serve"], env=env)
    assert r.exit_code == 1 and ran == [] and r.output.strip() == (
        'Two gateways answer as "gateway" on this compose network. Use one of gateway, gateway-nvidia and '
        "gateway-amd in COMPOSE_PROFILES.")
    monkeypatch.setattr(gpu.socket, "getaddrinfo", _answers("172.20.0.3", "172.20.0.3"))     # one gateway serves
    assert CliRunner().invoke(cli.app, ["serve"], env=env).exit_code == 0 and len(ran) == 1
    assert gpu.two_gateways(lambda *a, **k: (_ for _ in ()).throw(OSError())) is False


@pytest.mark.parametrize("image", [None, "nvidia"], ids=["cpu", "nvidia"])
def test_outside_compose_the_two_gateways_check_never_runs(monkeypatch, gw_cfg, image):
    """network = "tailscale" (the systemd gateway, and the default) never looks up the name "gateway"."""
    assert gw_cfg.network == "tailscale"
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr("steward_gateway.cli.api_key", lambda cfg: None)
    monkeypatch.setattr("steward_gateway.accelerator.available", lambda: "cuda")
    monkeypatch.setattr(gpu, "two_gateways", lambda *a, **k: pytest.fail("two_gateways asked outside compose"))
    monkeypatch.setattr(gpu.socket, "getaddrinfo", lambda *a, **k: pytest.fail("gateway looked up outside compose"))
    ran = []
    monkeypatch.setattr(serving, "run", lambda cfg, app: ran.append(cfg))
    env = {} if image is None else {"STEWARD_GATEWAY_GPU": image, "STEWARD_GPU_LICENSE_ACCEPTED": image}
    r = CliRunner().invoke(cli.app, ["serve"], env=env)
    assert r.exit_code == 0 and len(ran) == 1


@pytest.mark.parametrize("vendor, service", [("nvidia", "ollama-nvidia"), ("amd", "ollama-amd"), (None, "ollama")])
def test_serve_names_the_ollama_service_beside_its_image(monkeypatch, gw_cfg, tmp_path, vendor, service):
    """A GPU profile's Ollama starts only once its gateway is healthy (deploy/compose.yml), so the gateway's start line
    must not call it missing, and every pull command names the service that runs. The CPU image keeps "ollama"."""
    import httpx2
    from dataclasses import replace
    from steward_gateway import config
    from steward_gateway import ollama as ollama_module
    marker = tmp_path / ".dockerenv"
    marker.touch()
    monkeypatch.setattr(config, "CONTAINER_MARKERS", (marker,))
    monkeypatch.setattr(cli, "load_config", lambda: replace(gw_cfg, network="compose", host="0.0.0.0",
                                                            ollama_url="http://ollama:11434"))
    monkeypatch.setattr("steward_gateway.cli.api_key", lambda cfg: None)
    monkeypatch.setattr("steward_gateway.accelerator.available", lambda: "cuda")
    monkeypatch.setattr(gpu, "two_gateways", lambda: False)
    monkeypatch.setattr(serving, "run", lambda cfg, app: None)
    monkeypatch.setattr(cli, "local_model_line", ollama_module.local_model_line)   # conftest stubs it; Ollama is faked
    real_client = httpx2.Client
    up = {"tags": False}

    def ollama(request):
        if not up["tags"]:
            raise httpx2.ConnectError("refused")
        return httpx2.Response(200, json={"models": []})
    monkeypatch.setattr(httpx2, "Client", lambda: real_client(transport=httpx2.MockTransport(ollama)))
    env = {} if vendor is None else {"STEWARD_GATEWAY_GPU": vendor, "STEWARD_GPU_LICENSE_ACCEPTED": vendor}
    r = CliRunner().invoke(cli.app, ["serve"], env=env)
    assert r.exit_code == 0
    if vendor:
        assert "isn't answering" not in r.output and f"Ollama ({service}) starts once this gateway is healthy" in r.output
        assert "  docker compose run --rm ollama-pull " in r.output
    else:
        assert "Ollama isn't answering at http://ollama:11434" in r.output
    up["tags"] = True                                               # a gateway-only restart: Ollama already answers
    r = CliRunner().invoke(cli.app, ["serve"], env=env)
    assert r.exit_code == 0 and "  docker compose run --rm ollama-pull " in r.output


def test_one_gateway_with_an_ipv4_and_an_ipv6_address_is_still_one():
    both = lambda host, port, *a, **k: [(2, 1, 6, "", ("172.20.0.3", port)), (10, 1, 6, "", ("fd00::3", port, 0, 0))]
    assert gpu.two_gateways(both) is False
    two_v6 = lambda host, port, *a, **k: [(10, 1, 6, "", ("fd00::3", port, 0, 0)), (10, 1, 6, "", ("fd00::4", port, 0, 0))]
    assert gpu.two_gateways(two_v6) is True


@pytest.mark.parametrize("vendor, line", [
    ("nvidia", "This gateway image is for an NVIDIA GPU, but torch can't see one, so redaction runs on the CPU. Check "
               "the host's driver and the NVIDIA Container Toolkit (docs/guides/gpu.md, \"NVIDIA\")."),
    ("amd", "This gateway image is for an AMD GPU, but torch can't see one, so redaction runs on the CPU. Check "
            "/dev/kfd, /dev/dri and STEWARD_RENDER_GID (docs/guides/gpu.md, \"AMD\").")])
def test_a_gpu_image_that_sees_no_gpu_says_so_and_runs_on_the_cpu(monkeypatch, gw_cfg, vendor, line):
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr("steward_gateway.cli.api_key", lambda cfg: None)
    monkeypatch.setattr("steward_gateway.accelerator.available", lambda: "cpu")
    ran = []
    monkeypatch.setattr(serving, "run", lambda cfg, app: ran.append(cfg))
    r = CliRunner().invoke(cli.app, ["serve"], env={"STEWARD_GATEWAY_GPU": vendor, "STEWARD_GPU_LICENSE_ACCEPTED": vendor})
    assert r.exit_code == 0 and line in r.output and len(ran) == 1
    assert gpu.no_gpu_line({"STEWARD_GATEWAY_GPU": vendor}, lambda: "cuda") is None
    assert gpu.no_gpu_line({}, lambda: pytest.fail("torch asked without a GPU image")) is None
