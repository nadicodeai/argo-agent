# nix/tui.nix — Argo TUI (Ink/React) compiled with tsc and bundled
{ pkgs, argoNpmLib, ... }:
let
  src = ../ui-tui;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-4SaqBY9JhyzuYsvg6sUiXicJ14fauc/r3n96KfC2aE4=";
  };

  npm = argoNpmLib.mkNpmPassthru { folder = "ui-tui"; attr = "tui"; pname = "argo-tui"; };

  packageJson = builtins.fromJSON (builtins.readFile (src + "/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "argo-tui";
  inherit src npmDeps version;

  doCheck = false;
  npmFlags = [ "--legacy-peer-deps" ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/argo-tui

    # Single self-contained bundle built by scripts/build.mjs (esbuild).
    cp -r dist $out/lib/argo-tui/dist

    # package.json kept for "type": "module" resolution on `node dist/entry.js`.
    cp package.json $out/lib/argo-tui/

    runHook postInstall
  '';
})
