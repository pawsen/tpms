{
  description = "TPMS plotting (numpy + matplotlib) dev shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          py = pkgs.python3.withPackages (ps: with ps; [
            numpy
            matplotlib
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              py
            ];

            # Optional: nicer defaults for matplotlib (avoids some font warnings)
            # environment variables are fine to omit if you don't care.
            shellHook = ''
              # export MPLBACKEND=Agg
              echo "Python: $(python --version)"
            '';
          };
        }
      );
    };
}
