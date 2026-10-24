{
  description = "Souls of the Reaper - native Linux build and NixOS installer";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            # Toolchain (ReXGlue requires Clang >= 18)
            clang
            lld
            cmake
            ninja
            pkg-config
            # Qt6 installer (Tkinter remains a fallback).
            (python3.withPackages (ps: [ ps.tkinter ps.pyside6 ]))
            qt6.qtbase
            git

            # Linux windowing/display requirements (SDK uses SDL3 with Wayland + X11 fallback)
            gtk3
            libx11
            libxcb
            libxext
            libxrandr
            libxi
            libxcursor
            libxinerama
            libxscrnsaver
            libxfixes
            libxkbcommon

            # Native Wayland windowing and SDL's Wayland backend
            wayland
            wayland-scanner
            libdecor

            # Vulkan backend
            vulkan-loader
            vulkan-headers

            # OpenGL/GLX dispatch used by GTK when launched from Steam
            libglvnd
            mesa

            # SDL3 uses libudev to enumerate Linux input/HID devices,
            # including the Steam Controller and Steam Input virtual pads.
            udev

            # SDL3 audio backends enabled by the SDK
            alsa-lib
            libpulseaudio
            pipewire
          ];

          shellHook = ''
            export CC=clang
            export CXX=clang++
            # PySide6 ships the Python bindings, while the Qt platform plugins
            # live in qtbase. Without this, Qt cannot find libqwayland.so.
            export QT_PLUGIN_PATH="${pkgs.qt6.qtbase}/lib/qt-6/plugins:''${QT_PLUGIN_PATH:-}"
            export QT_QPA_PLATFORM_PLUGIN_PATH="${pkgs.qt6.qtbase}/lib/qt-6/plugins/platforms"
            # These libraries are dlopen()ed by the Vulkan loader/SDL3 rather
            # than linked, so put them on the loader search path.
            export LD_LIBRARY_PATH="${pkgs.vulkan-loader}/lib:${pkgs.libglvnd}/lib:${pkgs.mesa}/lib:${pkgs.libx11}/lib:${pkgs.libxcb}/lib:${pkgs.libxext}/lib:${pkgs.libxrandr}/lib:${pkgs.libxi}/lib:${pkgs.libxcursor}/lib:${pkgs.libxinerama}/lib:${pkgs.libxscrnsaver}/lib:${pkgs.libxfixes}/lib:${pkgs.libxkbcommon}/lib:${pkgs.wayland}/lib:${pkgs.libdecor}/lib:${pkgs.alsa-lib}/lib:${pkgs.libpulseaudio}/lib:${pkgs.pipewire}/lib:${pkgs.udev}/lib:''${LD_LIBRARY_PATH:-}"
            echo "Souls of the Reaper - Linux dev shell"
            echo "  ./port/codegen.sh    # transcode game/default.xex (needs game data)"
            echo "  ./port/build.sh      # build port/out/build/linux-amd64-relwithdebinfo/diablo3"
          '';
        };
      });

      packages = forAll (pkgs: {
        default = pkgs.stdenvNoCC.mkDerivation {
          pname = "souls-of-the-reaper-installer";
          version = "latest";
          dontUnpack = true;
          nativeBuildInputs = [ pkgs.makeWrapper ];
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/bin" "$out/share/applications"
            install -m755 ${./nix/launcher.sh} "$out/bin/souls-of-the-reaper"
            install -m644 ${./nix/souls-of-the-reaper.desktop} \
              "$out/share/applications/souls-of-the-reaper.desktop"
            wrapProgram "$out/bin/souls-of-the-reaper" \
              --prefix PATH : ${
                pkgs.lib.makeBinPath [
                  pkgs.bash
                  pkgs.coreutils
                  pkgs.curl
                  pkgs.gawk
                  pkgs.git
                  pkgs.gnutar
                  pkgs.gzip
                  pkgs.nix
                  pkgs.python3
                ]
              }
            runHook postInstall
          '';
          meta = {
            description = "NixOS installer/manager for the Souls of the Reaper Linux port";
            homepage = "https://github.com/ccgman123/Souls-of-the-Reaper";
            mainProgram = "souls-of-the-reaper";
            platforms = [ "x86_64-linux" ];
          };
        };
      });

      apps = forAll (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/souls-of-the-reaper";
        };
        install = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/souls-of-the-reaper";
        };
      });

      nixosModules.default =
        { pkgs, ... }:
        {
          environment.systemPackages = [
            self.packages.${pkgs.stdenv.hostPlatform.system}.default
          ];
        };
    };
}
