%global debug_package %{nil}
%global renpy_version 8.5.3
%global renpy_root %{_libexecdir}/tyranor-next-linux/renpy

Name:           tyranor-next-renpy-runtime
Version:        8.5.3
Release:        1%{?dist}
Summary:        Ren'Py runtime bundled for Tyranor Next Linux

License:        MIT AND LGPL-2.1-only
URL:            https://www.renpy.org/
Source0:        renpy-%{renpy_version}-sdk.tar.bz2

BuildArch:      x86_64
AutoReqProv:    yes

%description
Bundled Ren'Py 8.5.3 Linux x86_64 runtime used by Tyranor Next Linux.
Only the command-line runtime, Python runtime and required Ren'Py engine
modules are installed; SDK tutorials, documentation and non-Linux binaries
are omitted.

%prep
%autosetup -n renpy-%{renpy_version}-sdk

%install
install -d %{buildroot}%{renpy_root}/lib
install -m0755 renpy.sh renpy.py %{buildroot}%{renpy_root}/
sed -i '1c #!/usr/bin/python3' %{buildroot}%{renpy_root}/renpy.py
cp -a renpy gui sdk-fonts %{buildroot}%{renpy_root}/
cp -a lib/python3.12 lib/py3-linux-x86_64 %{buildroot}%{renpy_root}/lib/
install -Dpm0644 LICENSE.txt \
    %{buildroot}%{_licensedir}/%{name}/LICENSE.txt

install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/renpy <<EOF
#!/bin/sh
exec %{renpy_root}/renpy.sh "\$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/renpy

%files
%license %{_licensedir}/%{name}/LICENSE.txt
%{_bindir}/renpy
%{renpy_root}

%changelog
* Mon Nov 09 2026 Tyranor Next Linux contributors <noreply@localhost> - 8.5.3-1
- Bundle Ren'Py 8.5.3 Linux runtime
