# nix/packages.nix — Argo Agent package built with uv2nix
{ inputs, ... }:
{
  perSystem =
    { pkgs, inputs', ... }:
    let
      argoAgent = pkgs.callPackage ./argo-agent.nix {
        inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
        npm-lockfile-fix = inputs'.npm-lockfile-fix.packages.default;
        # Only embed clean revs — dirtyRev doesn't represent any upstream
        # commit, so comparing it would always claim "update available".
        rev = inputs.self.rev or null;
      };
    in
    {
      packages = {
        default = argoAgent;
        tui = argoAgent.argoTui;
        web = argoAgent.argoWeb;

        fix-lockfiles = argoAgent.argoNpmLib.mkFixLockfiles {
          packages = [ argoAgent.argoTui argoAgent.argoWeb ];
        };
      };
    };
}
