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


if __name__ == '__main__':
    unittest.main()
