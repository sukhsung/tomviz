import os
import shutil
import base64

from paraview import simple
from paraview.web.dataset_builder import ImageDataSetBuilder
from paraview.web.dataset_builder import CompositeDataSetBuilder
from paraview.web.dataset_builder import VTKGeometryDataSetBuilder

from tomviz import py2to3

DATA_DIRECTORY = 'data'
HTML_FILENAME = 'tomviz.html'
HTML_WITH_DATA_FILENAME = 'tomviz_data.html'


def web_export(executionPath, destPath, exportType, nbPhi, nbTheta):
    # Destination directory for data
    dest = '%s/data' % destPath

    # Extract initial setting for view
    view = simple.GetRenderView()
    viewState = {}
    for prop in ['CameraViewUp', 'CameraPosition']:
        viewState[prop] = tuple(view.GetProperty(prop).GetData())

    # Camera handling
    deltaPhi = int(360 / nbPhi)
    deltaTheta = int(180 / nbTheta)
    thetaMax = deltaTheta
    while thetaMax + deltaTheta < 90:
        thetaMax += deltaTheta
    camera = {
        'type': 'spherical',
        'phi': range(0, 360, deltaPhi),
        'theta': range(-thetaMax, thetaMax + 1, deltaTheta)
    }

    # Choose export mode:
    if exportType == 0:
        export_images(dest, camera)

    if exportType == 1:
        export_volume_exploration_images(dest, camera)

    if exportType == 2:
        export_contour_exploration_images(dest, camera)

    if exportType == 3:
        export_contours_geometry(dest)

    if exportType == 4:
        export_contour_exploration_geometry(dest)

    if exportType == 5:
        export_layers(dest, camera)

    # Setup application
    copy_viewer(destPath, executionPath)
    bundleDataToHTML(destPath)

    # Restore initial parameters
    for prop in viewState:
        view.GetProperty(prop).SetData(viewState[prop])

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def bundleDataToHTML(destinationPath):
    dataDir = os.path.join(destinationPath, DATA_DIRECTORY)
    srcHtmlPath = os.path.join(destinationPath, HTML_FILENAME)
    dstHtmlPath = os.path.join(destinationPath, HTML_WITH_DATA_FILENAME)
    webResources = ['<style>.webResource { display: none; }</style>']

    if os.path.exists(dataDir):
        for dirName, subdirList, fileList in os.walk(dataDir):
            for fname in fileList:
                fullPath = os.path.join(dirName, fname)
                filePath = os.path.relpath(fullPath, dataDir)
                relPath = '%s/%s' % (DATA_DIRECTORY, filePath)
                content = ''

                if fname.endswith('.json'):
                    with open(fullPath, 'r') as data:
                        content = data.read()
                else:
                    with open(fullPath, 'rb') as data:
                        dataContent = data.read()
                        if hasattr(dataContent, 'encode'):
                            dataContent = dataContent.encode()

                        content = base64.b64encode(dataContent)
                        content = content.decode().replace('\n', '')

                webResources.append(
                    '<div class="webResource" data-url="%s">%s</div>'
                    % (relPath, content))

    webResources.append('<script>ready()</script></body>')

    # Create new output file
    with open(srcHtmlPath, mode='r') as srcHtml:
        with open(dstHtmlPath, mode='w') as dstHtml:
            for line in srcHtml:
                if '</body>' in line:
                    for webResource in webResources:
                        dstHtml.write(webResource)
                else:
                    dstHtml.write(line)

    # Cleanup
    shutil.rmtree(dataDir)
    os.remove(srcHtmlPath)


def get_proxy(id):
    session = simple.servermanager.ActiveConnection.Session
    remoteObj = session.GetRemoteObject(int(id))
    return simple.servermanager._getPyProxy(remoteObj)


def copy_viewer(destinationPath, executionPath):
    searchPath = executionPath
    for upDirTry in range(4):
        searchPath = os.path.normpath(os.path.join(searchPath, '..'))
        for root, dirs, files in os.walk(searchPath):
            if HTML_FILENAME in files and root != destinationPath:
                srcFile = os.path.join(root, HTML_FILENAME)
                shutil.copy(srcFile, destinationPath)
                return


def add_scene_item(scene, name, proxy, view):
    hasNormal = False
    hasColor = False
    colors = {}
    representation = {}
    rep = simple.GetRepresentation(proxy, view)

    # Skip hidden object or volume
    if not rep.Visibility or rep.Representation == 'Volume':
        return

    for prop in ['Representation']:
        representation[prop] = rep.GetProperty(prop).GetData()

    pdInfo = proxy.GetPointDataInformation()
    numberOfPointArrays = pdInfo.GetNumberOfArrays()
    for idx in range(numberOfPointArrays):
        array = pdInfo.GetArray(idx)
        rangeValues = array.GetRange(-1)
        if array.Name == 'Normals':
            hasNormal = True
        if array.Name not in ['vtkValidPointMask', 'Normals']:
            hasColor = True
            if rangeValues[0] == rangeValues[1]:
                colors[array.Name] = {
                    'constant': rangeValues[0],
                    'location': 'POINT_DATA'
                }
            else:
                colors[array.Name] = {
                    'location': 'POINT_DATA',
                    'range': [i for i in rangeValues]
                }

    # Get information about cell data arrays
    cdInfo = proxy.GetCellDataInformation()
    numberOfCellArrays = cdInfo.GetNumberOfArrays()
    for idx in range(numberOfCellArrays):
        array = cdInfo.GetArray(idx)
        hasColor = True
        colors[array.Name] = {
            'location': 'CELL_DATA',
            'range': array.GetRange(-1)
        }

    # Make sure Normals are available if lighting by normals
    source = proxy
    if not hasColor or rep.Representation == 'Outline':
        colors = {'solid': {'constant': 0, 'location': 'POINT_DATA'}}
    elif 'light' in scene and 'normal' in scene['light'] and not hasNormal:
        rep.Visibility = 0
        surface = simple.ExtractSurface(Input=proxy)
        surfaceWithNormals = simple.GenerateSurfaceNormals(Input=surface)
        source = surfaceWithNormals

    scene['scene'].append({
        'name': name,
        'source': source,
        'colors': colors,
        'representation': representation
    })


def get_volume_piecewise(view):
    renderer = view.GetClientSideObject().GetRenderer()
    for volume in renderer.GetVolumes():
        if volume.GetClassName() == 'vtkVolume':
            return volume.GetProperty().GetScalarOpacity()
    return None


def get_contour():
    for key, value in py2to3.iteritems(simple.GetSources()):
        if 'FlyingEdges' in key[0]:
            return value
    return None

# -----------------------------------------------------------------------------
# Image based exporter
# -----------------------------------------------------------------------------


def export_images(destinationPath, camera):
    view = simple.GetRenderView()
    idb = ImageDataSetBuilder(destinationPath, 'image/jpg', camera)
    idb.start(view)
    idb.writeImages()
    idb.stop()

# -----------------------------------------------------------------------------
# Image based Volume exploration
# -----------------------------------------------------------------------------


def export_volume_exploration_images(destinationPath, camera):
    view = simple.GetRenderView()
    pvw = get_volume_piecewise(view)
    maxOpacity = 0.5
    nbSteps = 10
    step = 250.0 / float(nbSteps)
    span = step * 0.4
    values = [float(v + 1) * step for v in range(0, nbSteps)]
    if pvw:
        idb = ImageDataSetBuilder(destinationPath, 'image/jpg', camera)
        idb.getDataHandler().registerArgument(priority=1, name='volume',
                                              values=values, ui='slider',
                                              loop='reverse')
        idb.start(view)
        for volume in idb.getDataHandler().volume:
            pvw.RemoveAllPoints()
            pvw.AddPoint(float(volume) - span, 0)
            pvw.AddPoint(float(volume), maxOpacity)
            pvw.AddPoint(float(volume) + span, 0)
            pvw.AddPoint(255, 0)
            idb.writeImages()
        idb.stop()
    else:
        print('No Volume module available')

# -----------------------------------------------------------------------------
# Image based Contour exploration
# -----------------------------------------------------------------------------


def export_contour_exploration_images(destinationPath, camera):
    view = simple.GetRenderView()
    contour = get_contour()
    nbSteps = 10
    step = 250.0 / float(nbSteps)
    values = [float(v + 1) * step for v in range(0, nbSteps)]
    if contour:
        idb = ImageDataSetBuilder(destinationPath, 'image/jpg', camera)
        idb.getDataHandler().registerArgument(priority=1, name='contour',
                                              values=values, ui='slider',
                                              loop='reverse')
        idb.start(view)
        for contourValue in idb.getDataHandler().contour:
            contour.Value = [contourValue]
            idb.writeImages()
        idb.stop()
    else:
        print('No contour module available')

# -----------------------------------------------------------------------------
# Contours Geometry export
# -----------------------------------------------------------------------------


def export_contours_geometry(destinationPath):
    view = simple.GetRenderView()
    sceneDescription = {'scene': []}
    for key, value in simple.GetSources().iteritems():
        if key[0] == 'Contour':
            add_scene_item(sceneDescription, key[0], value, view)

    count = 1
    for item in sceneDescription['scene']:
        item['name'] += ' (%d)' % count
        count += 1

    # Create geometry Builder
    dsb = VTKGeometryDataSetBuilder(destinationPath, sceneDescription)
    dsb.start()
    dsb.writeData(0)
    dsb.stop()

# -----------------------------------------------------------------------------
# Contours Geometry export
# -----------------------------------------------------------------------------


def export_contour_exploration_geometry(destinationPath):
    contour = None
    for key, value in simple.GetSources().iteritems():
        if key[0] == 'Contour':
            contour = value

    if contour:
        sceneDescription = {
            'scene': [{
                'name': 'Contour',
                'source': contour,
                'colors': {
                    'Scalar': {
                        'constant': 0,
                        'location': 'POINT_DATA'
                    }
                }
            }]
        }
        dsb = VTKGeometryDataSetBuilder(destinationPath, sceneDescription)
        dsb.getDataHandler().registerArgument(priority=1, name='contour',
                                              values=range(25, 251, 25),
                                              ui='slider', loop='modulo')
        dsb.start()
        scalarContainer = sceneDescription['scene'][0]['colors']['Scalar']
        for contourValue in dsb.getDataHandler().contour:
            contour.Value = [contourValue]
            scalarContainer['constant'] = contourValue
            dsb.writeData()
        dsb.stop()

# -----------------------------------------------------------------------------
# Composite exporter
# -----------------------------------------------------------------------------


def export_layers(destinationPath, camera):
    view = simple.GetRenderView()
    fp = tuple(view.CameraFocalPoint)
    cp = tuple(view.CameraPosition)
    vu = tuple(view.CameraViewUp)
    sceneDescription = {
        'size': tuple(view.ViewSize),
        'light': ['intensity'],  # 'normal', intensity
        'camera': {
            'CameraViewUp': vu,
            'CameraPosition': cp,
            'CameraFocalPoint': fp
        },
        'scene': []
    }

    for key, value in py2to3.iteritems(simple.GetSources()):
        add_scene_item(sceneDescription, key[0], value, view)

    # Generate export
    dsb = CompositeDataSetBuilder(
        destinationPath, sceneDescription, camera, {}, {}, view)
    dsb.start()
    dsb.writeData()
    dsb.stop(compress=False)
