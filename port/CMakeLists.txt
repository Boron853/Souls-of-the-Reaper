# diablo3 - ReXGlue Recompiled Project

cmake_minimum_required(VERSION 3.25)
project(diablo3 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# SDL3 uses libudev to enumerate Linux input/HID devices (including the
# Steam Controller). CMake's check_include_file/find_library do not see the
# include and library paths from Nix's wrapped compiler, so point them at
# libudev explicitly.
if(UNIX AND NOT APPLE)
  find_package(PkgConfig QUIET)
  if(PkgConfig_FOUND)
    pkg_check_modules(UDEV QUIET libudev)
    if(UDEV_FOUND)
      include_directories(${UDEV_INCLUDE_DIRS})
      link_directories(${UDEV_LIBRARY_DIRS})
      list(APPEND CMAKE_REQUIRED_INCLUDES ${UDEV_INCLUDE_DIRS})
      set(CMAKE_LIBRARY_PATH "${UDEV_LIBRARY_DIRS}" ${CMAKE_LIBRARY_PATH})
    endif()
  endif()
endif()

include(rexglue.cmake)

# Sources
set(DIABLO3_SOURCES
    src/main.cpp
    src/kernel_overrides.cpp
    src/base_exit.cpp
)

if(WIN32)
    add_executable(diablo3 WIN32 ${DIABLO3_SOURCES})
else()
    add_executable(diablo3 ${DIABLO3_SOURCES})
endif()

rexglue_setup_target(diablo3)

# When building the SDK from source (REXSDK_DIR -> add_subdirectory), rexglue_configure_target
# adds rex_app.cpp which includes <imgui.h> and <rex/version.h>. In install mode those headers
# live in the SDK's flat include tree; in source mode they are split:
#   - imgui.h       -> exposed by the 'imgui' target (BUILD_INTERFACE)
#   - rex/version.h -> generated in <build>/rexglue-sdk/include, exposed by 'rexcore' PUBLIC
# Pass include dirs only (no object linking -> no duplicate symbols).
foreach(_dep rexcore imgui)
    if(TARGET ${_dep})
        target_include_directories(diablo3 PRIVATE
            $<TARGET_PROPERTY:${_dep},INTERFACE_INCLUDE_DIRECTORIES>)
    endif()
endforeach()

# The SDK sets $ORIGIN on the host's runpath but only stages runtime DLLs on
# Windows. On Linux, copy the shared runtime next to the executable so the
# built tree runs without LD_LIBRARY_PATH.
if(UNIX AND NOT APPLE AND TARGET rexruntime)
    add_custom_command(TARGET diablo3 POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:rexruntime>
            $<TARGET_FILE_DIR:diablo3>
        VERBATIM)
endif()
