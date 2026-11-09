if(DEFINED ENV{KRKR_ALSA_SYSROOT})
    set(system_prefix "$ENV{KRKR_ALSA_SYSROOT}")
else()
    set(system_prefix "/usr")
endif()

file(COPY "${system_prefix}/include/alsa"
     DESTINATION "${CURRENT_PACKAGES_DIR}/include")

if(EXISTS "${system_prefix}/include/sys/asoundlib.h")
    file(COPY "${system_prefix}/include/sys/asoundlib.h"
         DESTINATION "${CURRENT_PACKAGES_DIR}/include/sys")
endif()

file(GLOB asound_libraries
     "${system_prefix}/lib64/libasound.so.2*"
     "${system_prefix}/lib/libasound.so.2*")
list(FILTER asound_libraries EXCLUDE REGEX "libasound\\.so\\.2$")
list(GET asound_libraries 0 asound_library)
get_filename_component(asound_name "${asound_library}" NAME)
file(COPY "${asound_library}" DESTINATION "${CURRENT_PACKAGES_DIR}/lib")
file(CREATE_LINK "${asound_name}"
     "${CURRENT_PACKAGES_DIR}/lib/libasound.so.2" SYMBOLIC)
file(CREATE_LINK "libasound.so.2"
     "${CURRENT_PACKAGES_DIR}/lib/libasound.so" SYMBOLIC)

file(MAKE_DIRECTORY "${CURRENT_PACKAGES_DIR}/lib/pkgconfig")
if(EXISTS "${system_prefix}/lib64/pkgconfig/alsa.pc")
    file(COPY "${system_prefix}/lib64/pkgconfig/alsa.pc"
         DESTINATION "${CURRENT_PACKAGES_DIR}/lib/pkgconfig")
elseif(EXISTS "${system_prefix}/lib/pkgconfig/alsa.pc")
    file(COPY "${system_prefix}/lib/pkgconfig/alsa.pc"
         DESTINATION "${CURRENT_PACKAGES_DIR}/lib/pkgconfig")
endif()

if(EXISTS "${system_prefix}/share/licenses/alsa-lib/COPYING")
    file(INSTALL "${system_prefix}/share/licenses/alsa-lib/COPYING"
         DESTINATION "${CURRENT_PACKAGES_DIR}/share/${PORT}")
endif()
