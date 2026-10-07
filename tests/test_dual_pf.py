# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_dual_pf', ROOT/'scripts/prepare_dual_pf.py')
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)
env_spec = importlib.util.spec_from_file_location('dual_pf_env', ROOT/'scripts/render-dual-pf-env.py')
env_renderer = importlib.util.module_from_spec(env_spec)
env_spec.loader.exec_module(env_renderer)


class InputTests(unittest.TestCase):
    def test_patch_hashes(self):
        self.assertEqual(len(prep.inputs()['patches']), 4)

    def test_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT/'profiles', root/'profiles')
            shutil.copytree(ROOT/'patches', root/'patches')
            (root/'patches/nccl-2.30.7-dual-pf.patch').write_text('bad')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                prep.inputs(root)

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'fresh'):
                prep.prepare(Path(tmp), Path(tmp))

    @unittest.skipUnless(os.getenv('NCCL_SOURCE'), 'set NCCL_SOURCE to a local pinned NCCL checkout')
    def test_real_patch_stack_and_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'prepared'
            result = prep.prepare(Path(os.environ['NCCL_SOURCE']), output)
            self.assertEqual(result['tree'], prep.inputs()['patched_tree'])
            source = (output/'source/src/transport/net_ib/connect.cc').read_text()
            self.assertEqual(source.count('// Modified by switchless-nccl: bound switchless listener GID selection.'), 1)
            # Compile the real shared switchless predicate with stub parameters.
            # This also catches future drift in alias handling without a CUDA build.
            generic = (output/'source/src/transport/generic.cc').read_text()
            predicate = re.search(r'bool ncclSwitchlessRingOnly\(\) \{[^}]+\}', generic).group()
            self.assertIn('const bool strict = ncclSwitchlessRingOnly();', source)
            self.assertIn('switchlessListenerDevices(strict, extended, dev, ncclNMergedIbDevs)', source)
            alias = Path(tmp)/'alias.cc'
            alias.write_text('#include <cassert>\n#include "switchless_listener_contract.h"\n'
                'static int ring, legacy;\n'
                'int ncclParamSwitchlessRingOnly() { return ring; }\n'
                'int ncclParamSkipTreeConnect() { return legacy; }\n' + predicate + '\n'
                'int main() {\n'
                ' for (ring=0; ring<2; ++ring) for (legacy=0; legacy<2; ++legacy) {\n'
                '  const bool strict = ncclSwitchlessRingOnly();\n'
                '  assert(strict == (ring || legacy));\n'
                '  auto devices = switchlessListenerDevices(strict, false, 2, 4);\n'
                '  assert(devices.begin == (strict ? 0 : 2));\n'
                '  assert(devices.end == (strict ? 4 : 3));\n'
                '  unsigned char gids[4][16] = {}; char roots[4][11] = {};\n'
                '  if (strict) assert(switchlessValidateListener(gids, roots, 4, true));\n'
                ' }\n}\n')
            for test, path, extra in [
                ('codec', output/'source/tests/routing_handle/compat.cc', []),
                ('alias', alias, ['-I'+str(output/'source/src/transport/net_ib')]),
                ('listener', ROOT/'tests/dual_pf_listener.cc', ['-I'+str(output/'source/src/transport/net_ib')])]:
                exe = Path(tmp)/test
                subprocess.run(['c++', '-std=c++11', '-O2', '-Wall', '-Wextra', '-Werror',
                                *extra, str(path), '-o', str(exe)], check=True)
                subprocess.run([str(exe)], check=True)
            build = json.loads((output/'build-plan.json').read_text())
            self.assertTrue(build['status'].startswith('UNRUN'))
            self.assertEqual(build['argv'][0], 'make')


class ConfigurationTests(unittest.TestCase):
    @staticmethod
    def config():
        return dict(hcas=['mlx5_0', 'mlx5_1', 'mlx5_2', 'mlx5_3'],
                    fabric_cidr='192.0.2.0/23',
                    fabric_addresses=['192.0.2.1', '192.0.2.2', '192.0.3.1', '192.0.3.2'],
                    socket_ifname='eth0')

    def test_portable_output_and_exact_hca_selection(self):
        text = env_renderer.render(self.config())
        # Check shell semantics without loading a library or contacting a host.
        result = subprocess.run(['bash', '-c', 'export NCCL_IB_GID_INDEX=3\n' + text +
            'printf "%s\\n" "$NCCL_IB_HCA" "$NCCL_IB_ADDR_RANGE" "$NCCL_SOCKET_IFNAME" '
            '"$GLOO_SOCKET_IFNAME" "$NCCL_IB_EXTENDED_IPV4_GIDS" "${NCCL_IB_GID_INDEX-unset}"'],
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(),
                         ['=mlx5_0,mlx5_1,mlx5_2,mlx5_3', '192.0.2.0/23', '=eth0', 'eth0', '1', 'unset'])

    def test_invalid_sites_refused(self):
        variants = [
            {'hcas': ['mlx5_0']*4}, {'hcas': ['mlx5_0', 'mlx5_1', 'mlx5_2', 'x;touch /tmp/x']},
            {'socket_ifname': 'eth0,eth1'}, {'socket_ifname': '0123456789012345'},
            {'fabric_cidr': '192.0.2.1/23'}, {'fabric_cidr': '::/0'},
            {'fabric_cidr': '192.0.2.0/24'},
            {'fabric_addresses': ['192.0.2.1']*4},
            {'fabric_addresses': ['192.0.2.1', '192.0.2.2', '192.0.2.3', '192.0.2.4']},
            {'fabric_addresses': ['192.0.2.1', '192.0.2.2', '192.0.3.1', '192.0.3.255']},
            {'extra': 'unsupported'},
        ]
        for update in variants:
            with self.subTest(update=update), self.assertRaises((ValueError, TypeError)):
                env_renderer.render(dict(self.config(), **update))

    def test_cli_invalid_config_has_no_partial_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.json'
            path.write_text(json.dumps(dict(self.config(), socket_ifname='bad;command')))
            result = subprocess.run(['python3', str(ROOT/'scripts/render-dual-pf-env.py'), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')

if __name__ == '__main__':
    unittest.main()
