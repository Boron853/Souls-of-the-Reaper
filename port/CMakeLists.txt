# diablo3 - ReXGlue Recompiled Project

cmake_minimum_required(VERSION 3.25)
project(diablo3 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(SOULS_ENABLE_EXTRA_FEATURES "Enable optional PC game features" OFF)
option(SOULS_TITLE_UPDATE "Build the verified USA update" OFF)

if(SOULS_ENABLE_EXTRA_FEATURES AND NOT (WIN32 OR CMAKE_SYSTEM_NAME STREQUAL "Linux"))
    message(FATAL_ERROR "Extra features support Windows and Linux base-disc/update builds")
endif()
if(SOULS_ENABLE_EXTRA_FEATURES)
    set(SOULS_BASE_XEX "${CMAKE_CURRENT_SOURCE_DIR}/../game/Default.xex" CACHE FILEPATH
        "Game executable used to generate the selected optional hooks")
    # One profile per game build under src/features/versions/ holds the guest
    # addresses, structure offsets and executable hash the hooks depend on.
    set(SOULS_FEATURE_VERSION "" CACHE STRING "PC-feature version profile id (default: base, or update-usa with SOULS_TITLE_UPDATE)")
    if(NOT SOULS_FEATURE_VERSION)
        if(SOULS_TITLE_UPDATE)
            set(SOULS_FEATURE_VERSION update-usa)
        else()
            set(SOULS_FEATURE_VERSION base)
        endif()
    endif()
    include(src/features/versions/load_version.cmake)
    souls_load_feature_version(${SOULS_FEATURE_VERSION} _souls_version_header _souls_expected_hash _souls_hooks)
    if(NOT EXISTS "${SOULS_BASE_XEX}")
        message(FATAL_ERROR "Extra features require the selected game Default.xex; set SOULS_BASE_XEX")
    endif()
    file(SHA256 "${SOULS_BASE_XEX}" _souls_xex_hash)
    if(NOT _souls_xex_hash STREQUAL _souls_expected_hash)
        message(FATAL_ERROR "Extra-feature executable does not match the selected base-disc/update hook addresses")
    endif()
endif()

if(SOULS_TITLE_UPDATE)
    include(title_updates/rexglue.cmake)
else()
    # Every platform shares the pinned SDK and the base-disc codegen in generated/base.
    include(base/rexglue.cmake)
endif()

# Sources
set(DIABLO3_SOURCES
    src/main.cpp
    src/kernel_overrides.cpp
    src/window_features.cpp
)
if(SOULS_TITLE_UPDATE)
    list(APPEND DIABLO3_SOURCES src/title_update_exit.cpp)
else()
    list(APPEND DIABLO3_SOURCES src/base_exit.cpp)
endif()

if(WIN32)
    add_executable(diablo3 WIN32 ${DIABLO3_SOURCES})
else()
    add_executable(diablo3 ${DIABLO3_SOURCES})
endif()

rexglue_setup_target(diablo3)
if(SOULS_TITLE_UPDATE)
    target_compile_definitions(diablo3 PRIVATE SOULS_TITLE_UPDATE=1)
endif()

if(SOULS_ENABLE_EXTRA_FEATURES)
    if(SOULS_TITLE_UPDATE)
        set(_souls_init "${CMAKE_CURRENT_SOURCE_DIR}/generated/update/diablo3_init.cpp")
    else()
        set(_souls_init "${CMAKE_CURRENT_SOURCE_DIR}/generated/base/diablo3_init.cpp")
    endif()
    if(NOT EXISTS "${_souls_init}")
        message(FATAL_ERROR "Run platform codegen before enabling extra features")
    endif()
    file(READ "${_souls_init}" _souls_mappings)
    foreach(_hook IN LISTS _souls_hooks)
        string(FIND "${_souls_mappings}" "${_hook}" _hook_position)
        if(_hook_position EQUAL -1)
            message(FATAL_ERROR "Generated code is missing ${_hook}; regenerate the selected game code")
        endif()
    endforeach()
    target_sources(diablo3 PRIVATE
        src/features/pc_features.cpp
        src/features/pc_features_startup.cpp
        src/features/pc_features_storage.cpp)
    target_include_directories(diablo3 PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/souls_generated")
    target_compile_definitions(diablo3 PRIVATE SOULS_ENABLE_EXTRA_FEATURES=1)
    message(STATUS "Optional PC features enabled: render resolution and window mode menus, PC autosave wording and Extras version label")
endif()

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
