%global debug_package %{nil}
%global _hardened_build 1

Name:           tyranor-next-linux
Version:        1.0.0
Release:        7%{?dist}
Summary:        Native Linux multi-engine visual novel launcher

License:        GPL-2.0-only
URL:            https://github.com/Weiss-UltimateSavior/Tyranor-Next
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
Requires:       python3 >= 3.11
Requires:       python3-pyqt6 >= 6.7
Requires:       python3-pillow >= 10
Requires:       python3-requests >= 2.31
Requires:       python3-cryptography >= 42
Requires:       python3-lxml >= 5
Requires:       python3-pyqt6-webengine
Requires:       hicolor-icon-theme
Requires:       tyranor-next-renpy-runtime >= 8.5.3
Requires:       tyranor-next-krkr-runtime >= 0.0.6-4
%description
Tyranor Next Linux is a native Linux desktop port of the Tyranor Next
multi-engine visual novel launcher. It provides game library scanning,
engine detection, cover metadata, save versions, WebDAV synchronization,
XP3 archive tools and native Linux process launching without Android,
SAF, JNI or APK runtime dependencies.

%prep
%autosetup -n %{name}-%{version}

%build
%{__python3} -m pip wheel . \
    --no-deps \
    --no-build-isolation \
    --wheel-dir %{_builddir}/wheelhouse

%install
WHEEL="$(find %{_builddir}/wheelhouse -maxdepth 1 -name '*.whl' -print -quit)"
test -n "$WHEEL"
%{__python3} -m pip install \
    --root %{buildroot} \
    --prefix %{_prefix} \
    --no-deps \
    --no-index \
    --ignore-installed \
    "$WHEEL"

install -Dpm0644 packaging/io.github.tyranornext.linux.desktop \
    %{buildroot}%{_datadir}/applications/io.github.tyranornext.linux.desktop
install -Dpm0644 packaging/io.github.tyranornext.linux.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.tyranornext.linux.metainfo.xml
for size in 16 24 32 48 64 128 256 512; do
    install -Dpm0644 \
        "packaging/icons/${size}x${size}/io.github.tyranornext.linux.png" \
        "%{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/io.github.tyranornext.linux.png"
done
install -Dpm0644 tyranor/assets/icon.png \
    %{buildroot}%{_datadir}/icons/hicolor/1024x1024/apps/io.github.tyranornext.linux.png
for size in 16 24 32 48 64 128 256 512 1024; do
    ln -s io.github.tyranornext.linux.png \
        "%{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/tyranor-next.png"
done
install -Dpm0644 LICENSE \
    %{buildroot}%{_licensedir}/%{name}/LICENSE
install -d %{buildroot}%{_docdir}/%{name}
install -pm0644 README.md \
    %{buildroot}%{_docdir}/%{name}/

# The wheel entry point is valid, but Fedora requires the system interpreter
# and the pathfix flags instead of a build-environment shebang.
sed -i '1c #!/usr/bin/python3 -sP' %{buildroot}%{_bindir}/tyranor-next

%post
update-desktop-database &>/dev/null || :
gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor &>/dev/null || :

%postun
update-desktop-database &>/dev/null || :
gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor &>/dev/null || :

%files
%license %{_licensedir}/%{name}/LICENSE
%{_docdir}/%{name}/README.md
%{_bindir}/tyranor-next
%{python3_sitelib}/tyranor
%{python3_sitelib}/tyranor_next_linux-*.dist-info
%{_datadir}/applications/io.github.tyranornext.linux.desktop
%{_metainfodir}/io.github.tyranornext.linux.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/io.github.tyranornext.linux.png
%{_datadir}/icons/hicolor/*/apps/tyranor-next.png

%changelog
* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 1.0.0-7
- Store every engine's saves under the Tyranor Next data directory
- Migrate legacy game-local saves without overwriting managed saves

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 1.0.0-6
- Fix Tyrano save/load slots, menu controls and keyboard focus

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 1.0.0-5
- Install multi-size application icons and align desktop/window identities

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 1.0.0-4
- Fix Tyrano click handling after event-layer rebuilds
- Let KiriKiri select the system audio driver instead of forcing PulseAudio

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 1.0.0-3
- Fix embedded WebEngine startup and add file-backed Tyrano saves

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 1.0.0-2
- Bundle Ren'Py runtime dependency, ASAR web games and visible runtime filtering

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 1.0.0-1
- Initial native Linux RPM package
