import json
import adsk.core, adsk.fusion, adsk.cam, traceback
import os
from ...lib import fusion360utils as futil
from ... import config
import time
import random
from typing import List, Dict
import math
from adsk.cam import ToolLibrary, Tool, DocumentToolLibrary
from hashlib import sha256

app = adsk.core.Application.get()
ui: adsk.core.UserInterface = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_Sync_Library'
CMD_NAME = 'Sync Library'
CMD_Description = 'Sync Library'
IS_PROMOTED = True

WORKSPACE_ID = 'CAMEnvironment'
PANEL_ID = 'CAMManagePanel'
COMMAND_BESIDE_ID = ''

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

# Local list of event handlers used to maintain a reference so
# they are not released and garbage collected.
local_handlers = []

def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    control = panel.controls.addCommand(cmd_def, COMMAND_BESIDE_ID, False)
    control.isPromoted = IS_PROMOTED

def stop():
    # Get the various UI elements for this command
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    command_control = panel.controls.itemById(CMD_ID)
    command_definition = ui.commandDefinitions.itemById(CMD_ID)

    if command_control:
        command_control.deleteMe()

    if command_definition:
        command_definition.deleteMe()

def command_created(args: adsk.core.CommandCreatedEventArgs):
    # General logging for debug.
    # futil.log(f'{CMD_NAME} Command Created Event')
    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)

    inputs = args.command.commandInputs

    # Make a drop down for sync direction
    syncDirection_input = inputs.addDropDownCommandInput('syncDirection', 'Sync Direction', adsk.core.DropDownStyles.TextListDropDownStyle)
    syncDirection_input.listItems.add('Pull', True)
    syncDirection_input.listItems.add('Push', False)

    # Option to select which tooling library to use
    library_input = inputs.addDropDownCommandInput('library', 'Library', adsk.core.DropDownStyles.TextListDropDownStyle)
    # Get the list of tooling libraries
    libraries = get_tooling_libraries()
    # Format the list of libraries for display in the drop down
    library_input.tooltipDescription = 'Select the tool library you would like to replace from.'
    formatted_libraries = format_library_names(libraries)
    for library in formatted_libraries:
        library_input.listItems.add(library, True)
    # print them to the console for debug
    # futil.log(f'Available libraries: {libraries}')


def command_execute(args: adsk.core.CommandEventArgs):
    # General logging for debug
    cam = adsk.cam.CAM.cast(app.activeProduct)
    inputs = args.command.commandInputs
    syncDirection_input: adsk.core.DropDownCommandInput = inputs.itemById('syncDirection')
    syncDirection_type = syncDirection_input.selectedItem.name
    # futil.log(str(syncDirection_type))
    library_input: adsk.core.DropDownCommandInput = inputs.itemById('library')
    camManager = adsk.cam.CAMManager.get()
    libraryManager = camManager.libraryManager
    toolLibraries = libraryManager.toolLibraries
    libraries = get_tooling_libraries()
    formatted_libraries = format_library_names(libraries)
    library_index = formatted_libraries.index(library_input.selectedItem.name)
    library_url = adsk.core.URL.create(libraries[library_index])
    library = toolLibraries.toolLibraryAtURL(library_url)

    # sourceTool = None

    if syncDirection_type == 'Pull':
        sourceLibrary = library
        targetLibrary = cam.documentToolLibrary
    if syncDirection_type == 'Push':
        sourceLibrary = cam.documentToolLibrary
        targetLibrary = library

    for targetTool in targetLibrary:
            #naive matching - support more options and detect multiple matches
            toolComment = targetTool.parameters.itemByName('tool_comment').value.value
            for sourceTool in sourceLibrary:
                if toolComment == sourceTool.parameters.itemByName('tool_comment').value.value:
                    for toolParameter in targetTool.parameters:
                        if toolParameter.name == 'tool_assemblyGaugeLength': #best to just update body length
                            continue
                        try:
                            targetTool.parameters.itemByName(toolParameter.name).value.value = sourceTool.parameters.itemByName(toolParameter.name).value.value
                        except:
                            pass
                    futil.log(toolComment + ' parameters synced')
                    for sourceToolPreset in sourceTool.presets:
                        if not targetTool.presets.itemsByName(sourceToolPreset.name):
                            newPreset = targetTool.presets.add()
                            newPreset.name = sourceToolPreset.name
                            for parameter in sourceToolPreset.parameters:
                                newPreset.parameters.itemByName(parameter.name).value.value = sourceToolPreset.parameters.itemByName(parameter.name).value.value
                            futil.log(sourceToolPreset.name + ' added to ' + toolComment)
                    if syncDirection_type == 'Pull': #update tools in doc one at a time
                        cam.documentToolLibrary.update(targetTool, True)
    if syncDirection_type == 'Push': #update library all at once at end
        toolLibraries.updateToolLibrary(library_url, library)

    ui.messageBox(' See log for list of updated tools.')

# This event handler is called when the command terminates.
def command_destroy(args: adsk.core.CommandEventArgs):
    global local_handlers
    local_handlers = []
    # futil.log(f'{CMD_NAME} Command Destroy Event')

def get_tooling_libraries() -> List:
    # Get the list of tooling libraries
    camManager = adsk.cam.CAMManager.get()
    libraryManager = camManager.libraryManager
    toolLibraries = libraryManager.toolLibraries
    fusion360Folder = toolLibraries.urlByLocation(adsk.cam.LibraryLocations.CloudLibraryLocation)
    libraries = getLibrariesURLs(toolLibraries, fusion360Folder)
    fusion360Folder = toolLibraries.urlByLocation(adsk.cam.LibraryLocations.LocalLibraryLocation)
    libraries = libraries + getLibrariesURLs(toolLibraries, fusion360Folder)
    fusion360Folder = toolLibraries.urlByLocation(adsk.cam.LibraryLocations.ExternalLibraryLocation)
    libraries = libraries + getLibrariesURLs(toolLibraries, fusion360Folder)
    return libraries

def getLibrariesURLs(libraries: adsk.cam.ToolLibraries, url: adsk.core.URL):
    ''' Return the list of libraries URL in the specified library '''
    urls: list[str] = []
    libs = libraries.childAssetURLs(url)
    for lib in libs:
        urls.append(lib.toString())
    for folder in libraries.childFolderURLs(url):
        urls = urls + getLibrariesURLs(libraries, folder)
    return urls

def format_library_names(libraries: List) -> List:
    # Format the list of libraries for display in the drop down
    formatted_libraries = []
    for library in libraries:
        formatted_libraries.append(library.split('/')[-1])
    return formatted_libraries