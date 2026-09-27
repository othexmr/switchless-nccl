# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
import os
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
            for test, path, extra in [
                ('codec', output/'source/tests/routing_handle/compat.cc', []),
                ('listener', ROOT/'tests/dual_pf_listener.cc', ['-I'+str(output/'source/src/transport/net_ib')])]:
                exe = Path(tmp)/test
                subprocess.run(['c++', '-std=c++11', '-O2', '-Wall', '-Wextra', '-Werror',
                                *extra, str(path), '-o', str(exe)], check=True)
                subprocess.run([str(exe)], check=True)
            build = json.loads((output/'build-plan.json').read_text())
            self.assertTrue(build['status'].startswith('UNRUN'))
            self.assertEqual(build['argv'][0], 'make')


class HostedBuildTests(unittest.TestCase):
    def test_local_builds_retain_unique_names_and_distribution_notices(self):
        """Exercise the real build wrapper up to Docker using CPU-only stubs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'scripts').mkdir(); (root/'bin').mkdir()
            shutil.copy(ROOT/'scripts/build-dual-pf-ci.sh', root/'scripts')
            (root/'scripts/versions.sh').write_text('NCCL_COMMIT=pinned\nCUDA_IMAGE=unused\n')
            (root/'scripts/prepare_dual_pf.py').write_text(
                "import pathlib,sys\n"
                "out=pathlib.Path(sys.argv[sys.argv.index('--output')+1])\n"
                "(out/'source').mkdir(parents=True)\n"
                "for name in ['LICENSE.txt','ThirdPartyNotices.txt']:\n"
                " (out/'source'/name).write_text(name+' original bytes')\n")
            for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
                shutil.copy(ROOT/name, root/name)
            stubs = {
                'uname': 'if [ "$1" = -s ]; then echo Linux; else echo aarch64; fi',
                'git': 'exit 0',
                'docker': 'printf "%s\\n" "$@" >> "$DOCKER_CALLS"; exit 44',
                'file': 'exit 99', 'readelf': 'exit 99',
                'sha256sum': 'exit 99', 'strings': 'exit 99',
            }
            for name, body in stubs.items():
                path = root/'bin'/name
                path.write_text('#!/bin/sh\n'+body+'\n'); path.chmod(0o755)
            env = dict(os.environ, PATH=str(root/'bin')+os.pathsep+os.environ['PATH'],
                       DOCKER_CALLS=str(root/'docker-calls'))
            env.pop('GITHUB_RUN_ID', None); env.pop('GITHUB_RUN_ATTEMPT', None)
            names = []
            for index in range(2):
                out = root/f'build-{index}'
                result = subprocess.run(['bash', str(root/'scripts/build-dual-pf-ci.sh'), str(out)],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 44, result.stderr)
                names.append((out/'container-name.txt').read_text().strip())
                self.assertRegex(names[-1], r'^dual-pf-local-[0-9a-f]{32}-1$')
                self.assertEqual((out/'exit.txt').read_text(), 'exit_code=44\n')
                for name in ('LICENSE.txt', 'ThirdPartyNotices.txt'):
                    self.assertEqual((out/'licenses'/name).read_bytes(), (out/'source'/name).read_bytes())
                for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
                    self.assertEqual((out/'licenses'/name).read_bytes(), (ROOT/name).read_bytes())
            self.assertNotEqual(*names)
            calls = (root/'docker-calls').read_text().splitlines()
            self.assertEqual(calls.count('run'), 2)
            self.assertNotIn('rm', calls); self.assertNotIn('--rm', calls)
            for name in names:
                self.assertIn(name, calls)
            workflow = (ROOT/'.github/workflows/dual-pf.yml').read_text()
            self.assertIn('${{ runner.temp }}/dual-pf/licenses/', workflow)


if __name__ == '__main__':
    unittest.main()
