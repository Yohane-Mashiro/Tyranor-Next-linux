%global debug_package %{nil}
%global krkr_root %{_libexecdir}/tyranor-next-linux/krkrsdl3
%global upstream_commit be6db962263f37fff81618c4db6bbdb410196a42

Name:           tyranor-next-krkr-runtime
Version:        0.0.6
Release:        4.gitbe6db96%{?dist}
Summary:        KiriKiri SDL3 Linux runtime bundled for Tyranor Next

License:        BSD-3-Clause AND LicenseRef-krkrsdl3-supplemental
URL:            https://github.com/krkrsdl3/krkrsdl3
Source0:        krkrsdl3-runtime-%{version}-gitbe6db96-linux-x86_64.tar.gz

BuildArch:      x86_64
AutoReqProv:    yes
Requires:       alsa-lib

%description
Native Linux x86_64 KiriKiri runtime used by Tyranor Next Linux.
The package contains the krkrsdl3 executable, required runtime resources
and the upstream license. It is built from krkrsdl3 commit
%{upstream_commit}.

%prep
%autosetup -n krkrsdl3-runtime

%install
install -d %{buildroot}%{krkr_root}
install -m0755 krkrsdl3 %{buildroot}%{krkr_root}/krkrsdl3
cp -a Res %{buildroot}%{krkr_root}/Res
install -Dpm0644 LICENSE \
    %{buildroot}%{_licensedir}/%{name}/LICENSE
install -Dpm0644 README.upstream.md \
    %{buildroot}%{_docdir}/%{name}/README.upstream.md

install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/krkrsdl3 <<EOF
#!/bin/sh
exec %{krkr_root}/krkrsdl3 "\$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/krkrsdl3

%files
%license %{_licensedir}/%{name}/LICENSE
%{_docdir}/%{name}/README.upstream.md
%{_bindir}/krkrsdl3
%{krkr_root}

%changelog
* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 0.0.6-4.gitbe6db96
- Support redirected per-game save directories through TYRANOR_SAVE_DIR

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 0.0.6-3.gitbe6db96
- Enable ALSA audio output and automatic audio-device fallback

* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 0.0.6-2.gitbe6db96
- Rebuild SDL3 with Wayland and X11 video backends
- Build native Linux x86_64 krkrsdl3 runtime
