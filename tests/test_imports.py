"""
Test that all modules can be imported correctly
Run this after installing dependencies to validate the setup
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_core_imports():
    """Test core module imports"""
    print("Testing core imports...")
    from core.config import settings
    from core.models import FuzzSession, TestCase, CrashReport
    from core.plugin_loader import plugin_manager
    from core.corpus.store import CorpusStore
    from core.engine.mutators import MutationEngine, BitFlipMutator
    from core.engine.orchestrator import orchestrator
    print("✓ Core imports successful")


def test_agent_imports():
    """Test agent module imports"""
    print("Testing agent imports...")
    from agent.monitor import ProcessMonitor, TargetExecutor
    print("✓ Agent imports successful")


def test_plugin_discovery():
    """Test plugin discovery"""
    print("Testing plugin discovery...")
    from core.plugin_loader import plugin_manager

    plugins = plugin_manager.discover_plugins()
    print(f"  Found {len(plugins)} plugins: {plugins}")

    if "simple_tcp" in plugins:
        plugin = plugin_manager.load_plugin("simple_tcp")
        print(f"  ✓ Loaded plugin: {plugin.name}")
        print(f"    - Data model blocks: {len(plugin.data_model.get('blocks', []))}")
        print(f"    - Seeds: {len(plugin.data_model.get('seeds', []))}")
        print(f"    - States: {plugin.state_model.get('states', [])}")
    print("✓ Plugin discovery successful")


def test_mutation_engine():
    """Test mutation engine"""
    print("Testing mutation engine...")
    from core.engine.mutators import MutationEngine

    seeds = [b"TEST1234", b"HELLO", b"WORLD"]
    engine = MutationEngine(seeds)

    test_case = engine.generate_test_case(seeds[0])
    print(f"  Generated test case: {len(test_case)} bytes")
    print("✓ Mutation engine successful")


def test_corpus_store():
    """Test corpus store"""
    print("Testing corpus store...")
    from core.corpus.store import CorpusStore
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CorpusStore(Path(tmpdir))
        seed_id = store.add_seed(b"TEST_SEED", metadata={"source": "test"})
        print(f"  Added seed: {seed_id[:16]}...")

        retrieved = store.get_seed(seed_id)
        assert retrieved == b"TEST_SEED", "Seed retrieval failed"
        print("  ✓ Seed storage and retrieval works")

        stats = store.get_corpus_stats()
        print(f"  Stats: {stats}")
    print("✓ Corpus store successful")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Fuzzer MVP - Import and Integration Tests")
    print("=" * 60 + "\n")

    try:
        test_core_imports()
        print()

        test_agent_imports()
        print()

        test_plugin_discovery()
        print()

        test_mutation_engine()
        print()

        test_corpus_store()
        print()

        print("=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print("\nThe MVP is ready to run!")
        print("Next steps:")
        print("  1. Start the target: python tests/simple_tcp_server.py")
        print("  2. Start the core: python -m core.api.server")
        print("  3. Open browser: http://localhost:8000")

    except ImportError as e:
        print(f"\n✗ Import Error: {e}")
        print("\nPlease install dependencies first:")
        print("  pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Test Failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
