%% *Matlab Live Tutorial*
% Below, you will find a quick tutorial to view the _C. elegans_ behavior data 
% and _E. coli_ fluorescence imaging data which relates to:
%% 
% * Paper: <https://doi.org/10.7554/eLife.103191 https://doi.org/10.7554/eLife.103191>
% * Dataset: <https://ndi-cloud.com/datasets/10.63884/ndic.2025.pb77mj2s https://doi.org/10.63884/ndic.2025.pb77mj2s>
%% Import the NDI dataset
% Define the dataset path and id.

% Choose the folder where the dataset is (or will be) stored
dataPath = fullfile(userpath,'Datasets'); % (e.g. /Users/myusername/Documents/MATLAB/Datasets)
datasetId = '682e7772cdf3f24938176fac';
datasetPath = fullfile(dataPath,datasetId);
% Download or load the NDI dataset 
% The first time you try to access the data, it needs to be downloaded from 
% <https://ndi-cloud.com/ NDI Cloud>. This will take several minutes. Once you 
% have the *dataset* downloaded, every other time you examine the data you can 
% just load it.

if isfolder(datasetPath)
    % Load if already downloaded
    dataset = ndi.dataset.dir(datasetPath);
else
    % Download
    if ~isfolder(dataPath), mkdir(dataPath); end
    dataset = ndi.cloud.downloadDataset(datasetId,dataPath);
end
% Retrieve the NDI session
% A *dataset* can have multiple *sessions*. This *dataset* has one *session* 
% for _C. elegans_ behavior and one *session* for _E. coli_ fluorescence imaging 
% data.

% Retrieve the sessions from this dataset
[session_ref,session_list] = dataset.session_list();
session_Celegans = dataset.open_session(session_list{contains(session_ref,'Celegans')});
session_Ecoli = dataset.open_session(session_list{contains(session_ref,'Ecoli')});
% View NDI file types
% Each NDI *dataset* is composed of .json documents and associated binary files. 
% Let's start by taking a look at the *document* types in this *dataset*. We'll 
% subsequently explore each of these below.

[docTypes,docCounts] = ndi.fun.doc.getDocTypes(dataset);
documentsNDI = table(docTypes,docCounts)
% View ontology term definitions
% Most of the metadata about these experiments are stored in |ontologyTableRow| 
% documents|.|We can look at the variables stored in all |ontologyTableRow| documents 
% and their well-defined meanings linked to an *ontology*.

% Get list of all variables
[fullNames,~,ontologyNodes] = ndi.fun.doc.ontologyTableRowVars(dataset);
%%
% Select a variable to view it's definition
fullName = fullNames(3);

% Look up the variable in the ontology
termIndex = strcmp(fullNames,fullName{1});
termID = ontologyNodes{termIndex};
[id,name,~,definition,~,shortName] = ndi.ontology.lookup(termID);

% Display the variable's id, name, definition, and short name
variableInfo = cell2table({id,name,definition,shortName}',...
    'RowNames',{'id','name','definition','shortName'},...
    'VariableNames',{'value'})
%% View _C. elegans_ dataset
% In these next few sections we will look at the _C. elegans_ *session*. Later, 
% we will look at the _E. coli_ *session*.
% Retrieve experiment metadata
% Most of the metadata about these experiments such as information about the 
% agar plates used for cultivation and behavioral assay of the animals is stored 
% in |ontologyTableRow| documents. Each document contains one row of data. We'll 
% start by retrieving the information from these documents and placing them in 
% their respective tables. The _C. elegans_ *dataset* has 6 different data tables 
% which store information related to the 1) *subjects*, 2) cultivation plates, 
% 3) behavior plates, 4) bacterial patches, 5) mapping of plates to subjects, 
% and 6) analysis of patch encounters. We'll walk through retrieving each of these.

% Get documents/table
query = ndi.query('','isa','ontologyTableRow');
docs = session_Celegans.database_search(query);
[dataTables,docIDs] = ndi.fun.doc.ontologyTableRowDoc2Table(docs); % this may take a minute

% Add relevant document identifiers
dataTables{1} = addvars(dataTables{1},docIDs{1}',...
    'NewVariableNames','BacterialPatchDocumentIdentifier'); % add patch document identifier
dataTables{2} = addvars(dataTables{2},docIDs{2}',...
    'NewVariableNames','BacterialPlateDocumentIdentifier'); % add plate document identifier
dataTables{3} = addvars(dataTables{3},docIDs{3}',...
    'NewVariableNames','BacterialPlateDocumentIdentifier'); % add plate document identifier
% View subject summary table
% Each individual animal is referred to as a *subject* and has a unique alphanumeric 
% |SubjectDocumentID| and |SubjectLocalID|. This dataset contains |ontologyTableRow*,*| 
% |subject|, |openminds_subject|, and |openminds| documents which store metadata 
% about each *subject* including their species, strain, genetic strain type, and 
% biological sex which are linked to well-defined ontologies such as NCBI and 
% WormBase. Additionally, metadata about any *treatments* that a *subject* received 
% such as food deprivation are stored in |treatment| documents. A summary table 
% showing the metadata for each *subject* can be viewed below.

% View summary table of all subject metadata
subjectSummary = ndi.fun.docTable.subject(session_Celegans); % this will take a minute
subjectTable = ndi.fun.table.join({dataTables{6},subjectSummary}) % adds subject metadata to subject table
% Filter subjects
% We have created tools to filter a table by it's values. Try finding *subjects* 
% matching a given criterion.

% Search for subjects
columnNamesSubject = subjectTable.Properties.VariableNames;
columnName = columnNamesSubject(5);
dataValue = "PR811";
rowInd = ndi.fun.table.identifyMatchingRows(subjectTable,...
    columnName{1},dataValue,'stringMatch','contains');
filteredSubjects = subjectTable(rowInd,:)
% View bacterial plate summary tables
% Let's combine all of the information about the behavior plates and patches.

behaviorPlateTable = ndi.fun.table.join(dataTables(1:2)) % add patch data to behavior plates
%% 
% As well as the cultivation plates.

cultivationPlateTable = dataTables{3} % cultivation plate data
%% 
% We also have a table that maps each subject to its respective cultivation 
% and behavior plates using their |SubjectDocumentIdentifier| and |BacterialPlateDocumentIdentifier|.

subjectPlateTable = dataTables{4} % subject to plate mapping
% Retrieve _C. elegans_ subject behavior
% Now let's choose a *subject* and look at all of the information we have available 
% in the dataset.

% Choose a subject to view its behavior data and metadata
subjectLocalIDs = subjectTable.SubjectLocalIdentifier;
subjectLocalID =subjectLocalIDs(360);
% Get subject and bacterial plate metadata

% Get subject document id
indSubjectTable = strcmp(subjectTable.SubjectLocalIdentifier,subjectLocalID{1});
subject_id = subjectTable.SubjectDocumentIdentifier{indSubjectTable};

% Get cultivation and behavior plate ids
indSubjectPlateTable = strcmp(subjectPlateTable.SubjectDocumentIdentifier,subject_id);
plateDocumentIDs = subjectPlateTable.BacterialPlateDocumentIdentifier(indSubjectPlateTable);
indCultivationPlateTable = find(ndi.fun.table.identifyMatchingRows(cultivationPlateTable,...
    'BacterialPlateDocumentIdentifier',plateDocumentIDs),1);
cultivationPlate_id = cultivationPlateTable.BacterialPlateDocumentIdentifier(indCultivationPlateTable);
indBehaviorPlateTable = find(ndi.fun.table.identifyMatchingRows(behaviorPlateTable,...
    'BacterialPlateDocumentIdentifier',plateDocumentIDs),1);
behaviorPlate_id = behaviorPlateTable.BacterialPlateDocumentIdentifier(indBehaviorPlateTable);

% Retrieve subject metadata
currentSubject = subjectTable(indSubjectTable,:)
% Retrieve plate metadata
currentPlates = ndi.fun.table.vstack({cultivationPlateTable(indCultivationPlateTable,:),...
    behaviorPlateTable(indBehaviorPlateTable,:)})
% Get position of subject over time
% In the NDI framework, an *element* is a physical (e.g. an instrument that 
% takes a measurement or produces a stimulus) or inferred object (e.g. simulated 
% data). In these experiments, there are 2 element types:
%% 
% # |position|
% # |distance|
%% 
% Each subject is linked to a unique set of elements. The *position* elements 
% in this dataset are connected to the X,Y coordinate location of each *subject* 
% over time in the behavioral video recording. The *distance* elements in this 
% dataset are connected to the distance between each *subject* and the nearest 
% bacterial patch. For now, let's read the timeseries of this subject's *position* 
% element.

% Get the position element document (one per subject)
queryDocType = ndi.query('element.type','exact_string','position');
queryDependency = ndi.query('','depends_on','subject_id',subject_id);
positionDoc = session_Celegans.database_search(queryDocType & queryDependency);

% Convert to NDI object
positionElement = ndi.database.fun.ndi_document2ndi_object(positionDoc{1}, session_Celegans);

% Read position timeseries
[position,time] = positionElement.readtimeseries(1,-Inf,Inf);
%% 
% Each |position| *element* is associated with a |position_metadata| document 
% which specifies what the |position| *timeseries* is tracking along with defining 
% the dimensions and units.

% Get the position_metadata document (one per subject)
queryDocType = ndi.query('','isa','position_metadata');
queryDependency = ndi.query('','depends_on','element_id',positionElement.id);
doc = session_Celegans.database_search(queryDocType & queryDependency);

% Get position_metadata ontology nodes
position_metadata = doc{1}.document_properties.position_metadata;
metadataFields = fields(position_metadata);
positionMetadata = {};
for i = 1:numel(metadataFields)
    termIDs = strsplit(position_metadata.(metadataFields{i}),',');
    for j = 1:numel(termIDs)
        [id,name,~,definition,~,shortName] = ndi.ontology.lookup(termIDs{j});

        % Display the variable's id, name, definition, and short name
        positionMetadata{end+1} = cell2table({metadataFields{i},id,name,definition,shortName},...
            'VariableNames',{'field','id','name','definition','shortName'});
    end
end
positionMetadata = ndi.fun.table.vstack(positionMetadata)
% Get associated video and image metadata
% An additional *document* type known as |imageStack| contains an image or video 
% and its relevant metadata associated with the behavioral video recordings. |ontologyLabel| 
% documents are used to add relevant ontological labels to each image and video 
% to describe the file.

% Query imageStack documents
queryDocType = ndi.query('','isa','imageStack');
queryDependency = ndi.query('','depends_on','document_id',behaviorPlate_id);
imageStackDocs = session_Celegans.database_search(queryDocType & queryDependency);

% Query ontologyLabel documents (used to label imageStack)
queryDocType = ndi.query('','isa','ontologyLabel');
labelDocs = session_Celegans.database_search(queryDocType);
labelDocs_dependency = cellfun(@(doc) doc.dependency_value('document_id'),labelDocs,'UniformOutput',false);

% Create imageStack metadata table
imageStackParameters = cell(size(imageStackDocs));
for i = 1:numel(imageStackDocs)
    indLabel = strcmp(labelDocs_dependency,imageStackDocs{i}.id);
    imageTerm = labelDocs{indLabel}.document_properties.ontologyLabel.ontologyNode;
    [id,name,~,definition,~,shortName] = ndi.ontology.lookup(imageTerm);
    formatTerm = imageStackDocs{i}.document_properties.imageStack.formatOntology;
    [~,~,~,~,format] = ndi.ontology.lookup(formatTerm); format = lower(format{1});
    label = cell2table({id,name,definition,shortName,format},...
        'VariableNames',{'id','name','definition','shortName','format'});
    metadata = vlt.data.flattenstruct2table(imageStackDocs{i}.document_properties.imageStack_parameters);
    imageStackParameters{i} = [label,metadata];
end
imageStackParameters = ndi.fun.table.vstack(imageStackParameters)
% Plot an image/mask with subject position

% Choose an image/video type
imageNames = imageStackParameters.name;
imageName = imageNames(3);
indImage = strcmp(imageStackParameters.name,imageName{1});
imageFormat = imageStackParameters.format{indImage};

% Get image data
doc = imageStackDocs{indImage};
[imageStack,imageStack_info] = ndi.fun.data.readImageStack(session_Celegans,doc,imageFormat);
if isa(imageStack,'VideoReader')
    image = read(imageStack,1); % first frame
else
    image = imageStack;
end

% Plot image and position
figure;
image = mat2gray(image);
imshow(flip(image));
hold on;
set(gca,'YDir','normal','XTick',[],'YTick',[],...
    'XLim',[1 size(image,1)],'YLim',[1 size(image,2)]);
bins = linspace(min(time),max(time),60);
c = jet(length(bins));
for j = 1:length(bins)-1
    ind = time >= bins(j) & time <= bins(j+1);
    plot(position(ind,1),position(ind,2),'Color',c(j,:),'LineWidth',1);
end
% Play video of the subject

% Get video
imageName = 'C. elegans behavioral assay: video recording';
indImage = strcmp(imageStackParameters.name,imageName);
imageFormat = imageStackParameters.format{indImage};
doc = imageStackDocs{indImage};
imageStack = ndi.fun.data.readImageStack(session_Celegans,doc,imageFormat);

% Play video with overlaid track
figure;
im = imshow(flip(mat2gray(read(imageStack,1))));
hold on;
t = title(['time = ',char(duration(0,0,0))]);
p = plot(position(1,1),position(1,2),'r','LineWidth',2);
set(gca,'YDir','normal','XTick',[],'YTick',[],...
    'XLim',[1 size(image,1)],'YLim',[1 size(image,2)]);
for i = 1:10:imageStack.NumFrames
    im.CData = flip(mat2gray(read(imageStack,i)));
    p.XData = position(1:i,1);
    p.YData = position(1:i,2);
    t.String = ['time = ',char(duration(0,0,time(i)))];
    drawnow;
end
% Get distance to patch edge over time
% Now let's take a look at the |distance| *element* timeseries and it's associated. 
% Each |position| *element* is associated with a |distance_metadata| which specifies 
% what the |distance| *timeseries* is tracking along with defining the dimensions 
% and units.

% Get the position element document (one per subject)
queryDocType = ndi.query('element.type','exact_string','distance');
queryDependency = ndi.query('','depends_on','subject_id',subject_id);
distanceDoc = session_Celegans.database_search(queryDocType & queryDependency);

% Convert to NDI object
distanceElement = ndi.database.fun.ndi_document2ndi_object(distanceDoc{1}, session_Celegans);

% Read distance timeseries
[distance,time,timeref] = distanceElement.readtimeseries(1,-Inf,Inf);

% Get the distance_metadata document (one per subject)
queryDocType = ndi.query('','isa','distance_metadata');
queryDependency = ndi.query('','depends_on','element_id',distanceElement.id);
doc = session_Celegans.database_search(queryDocType & queryDependency);

% Get distance_metadata ontology nodes
distance_metadata = doc{1}.document_properties.distance_metadata;
metadataFields = fields(distance_metadata);
distanceMetadata = {};
for i = 1:numel(metadataFields)
    if contains(metadataFields{i},'ontologyNode') || contains(metadataFields{i},'unit')
    termIDs = strsplit(distance_metadata.(metadataFields{i}),',');
    for j = 1:numel(termIDs)
        [id,name,~,definition,~,shortName] = ndi.ontology.lookup(termIDs{j});

        % Display the variable's id, name, definition, and short name
        distanceMetadata{end+1} = cell2table({metadataFields{i},id,name,definition,shortName},...
            'VariableNames',{'field','id','name','definition','shortName'});
    end
    end
end
distanceMetadata = ndi.fun.table.vstack(distanceMetadata)
% Get distance_metadata mapping
distanceMap_A = cell2table([num2cell(distance_metadata.integerIDs_A),...
    strsplit(distance_metadata.ontologyStringValues_A,',')'],...
    'VariableNames',{'ObjectNum_A',distanceMetadata.shortName{1}}); % get map
distanceMap_A = ndi.fun.table.join({distanceMap_A,subjectTable}) % add subject data
distanceMap_B = cell2table([num2cell(distance_metadata.integerIDs_B),...
    strsplit(distance_metadata.ontologyStringValues_B,',')'],...
    'VariableNames',{'ObjectNum_B',distanceMetadata.shortName{2}}); % get map
distanceMap_B = ndi.fun.table.join({distanceMap_B,behaviorPlateTable}) % add patch data
% Plot distance
figure; 
ax1 = subplot(211); hold on
yline(0,'k')
bins = linspace(min(time),max(time),60);
c = jet(length(bins));
for j = 1:length(bins)-1
    ind = time >= bins(j) & time <= bins(j+1);
    p = plot(time(ind),distance(ind,1),'Color',c(j,:),'LineWidth',1);
end
xlabel('time (s)'); ylabel('distance to patch edge (pixels)'); xlim(prctile(time,[0 100])); 
ax2 = subplot(212); plot(time,distance(:,3),'k','LineWidth',1);
xlabel('time (s)'); ylabel('closest patch #'); xlim(prctile(time,[0 100]));
% Get analysis of patch encounters
% Finally, let's view the analysis of patch encounters for this *subject*. This 
% data is stored in |ontologyTableRow| documents.

encounterTable = dataTables{5}; % get ontologyTableRow table
indEncounterTable = ndi.fun.table.identifyMatchingRows(encounterTable,...
    'SubjectDocumentIdentifier',subject_id); 
currentEncounters = encounterTable(indEncounterTable,:); % get rows associated with subject
currentEncounters = ndi.fun.table.join({currentEncounters,behaviorPlateTable}) % add patch data
%% View _E. coli_ dataset
% Now let's switch over to the _E. coli_ dataset.
% View strains
% Let's look at |openminds| strain information.

[strainTable,strainDocIDs] = ndi.fun.docTable.openminds(session_Ecoli,'Strain');
strainTable{:,'BacterialStrainDocumentIdentifier'} = strainDocIDs % add document ids
% Retrieve experiment metadata
% The _E. coli_ *dataset* has 3 different data tables which store information 
% related to the 1) bacterial plates, 2) microscopy images, 3) analysis of patches 
% in each image. Let's combine all of the data into a big table with one row per 
% patch per time point and add the relevant strain information.

% Get documents/table
query = ndi.query('','isa','ontologyTableRow');
docs = session_Ecoli.database_search(query);
[dataTables,docIDs] = ndi.fun.doc.ontologyTableRowDoc2Table(docs);

% Add relevant document identifiers
dataTables{2} = addvars(dataTables{2},docIDs{2}',...
    'NewVariableNames','ImageDocumentIdentifier'); % add image document identifier

% Combine tables
bacteriaTable = ndi.fun.table.join([dataTables([3,2,1]);{strainTable}])
% Get microscopy image metadata
% We also have |imageStack| documents which contain images and their relevant 
% metadata.

% Choose an image to view its properties
imageIDs = unique(bacteriaTable.MicroscopyImageIdentifier);
imageID = imageIDs(36);
indImage = find(strcmp(bacteriaTable.MicroscopyImageIdentifier,imageID{1}),1);
image_id = bacteriaTable.ImageDocumentIdentifier{indImage};
imageTable = bacteriaTable(indImage,:);

% Query documents
queryDocType = ndi.query('','isa','imageStack');
queryDependency = ndi.query('','depends_on','document_id',image_id);
imageStackDocs = session_Ecoli.database_search(queryDocType & queryDependency);

% Query ontologyLabel documents (used to label imageStack)
queryDocType = ndi.query('','isa','ontologyLabel');
labelDocs = session_Ecoli.database_search(queryDocType);
labelDocs_dependency = cellfun(@(doc) doc.dependency_value('document_id'),labelDocs,'UniformOutput',false);

% Create imageStack metadata table
imageStackParameters = cell(size(imageStackDocs));
for i = 1:numel(imageStackDocs)
    indLabel = strcmp(labelDocs_dependency,imageStackDocs{i}.id);
    imageTerm = labelDocs{indLabel}.document_properties.ontologyLabel.ontologyNode;
    [id,name,~,definition,~,shortName] = ndi.ontology.lookup(imageTerm);
    formatTerm = imageStackDocs{i}.document_properties.imageStack.formatOntology;
    [~,~,~,~,format] = ndi.ontology.lookup(formatTerm); format = lower(format{1});
    label = cell2table({id,name,definition,shortName,format},...
        'VariableNames',{'id','name','definition','shortName','format'});
    metadata = vlt.data.flattenstruct2table(imageStackDocs{i}.document_properties.imageStack_parameters);
    imageStackParameters{i} = [label,metadata];
end
imageStackParameters = ndi.fun.table.vstack(imageStackParameters)
% Plot an image or mask

% Choose an image/video type
imageNames = imageStackParameters.name;
imageName = imageNames(1);
indImage = strcmp(imageStackParameters.name,imageName{1});
imageFormat = imageStackParameters.format{indImage};

% Get image data
doc = imageStackDocs{indImage};
[imageStack,imageStack_info] = ndi.fun.data.readImageStack(session_Celegans,doc,imageFormat);

% Plot image
figure;
imagesc(imageStack); colormap(gray); colorbar;
t = title({['target OD_{600} at seeding = ',num2str(imageTable.BacterialOD600TargetAtSeeding)],...
    ['growth time at room temp = ',char(duration(imageTable.BacteriaGrowthDurationAfterSeeding,0,0))]});
set(gca,'YDir','normal','XTick',[],'YTick',[]);
