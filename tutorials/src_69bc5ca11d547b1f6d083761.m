%% *Matlab Live Tutorial*
% Below, you will find a quick tutorial to view the _C. elegans_ data which 
% relates to:
%% 
% * Paper: <https://www.biorxiv.org/content/10.1101/2025.02.26.640282v3 https://www.biorxiv.org/content/10.1101/2025.02.26.640282v3>
% * Dataset: <https://doi.org/10.63884/ndic.2026.0oxgzbjb https://doi.org/10.63884/ndic.2026.0oxgzbjb>
%% Download NDI
% In order to view the dataset, you will need access to the NDI platform. Follow 
% the instructions found at <https://vh-lab.github.io/NDI-matlab/NDI-matlab/installation/ 
% https://vh-lab.github.io/NDI-matlab/NDI-matlab/installation/> to download NDI 
% and gain access to the suite of tools we have created!
%% Import the NDI dataset
% Define the dataset path and id.

% Choose the folder where the dataset is (or will be) stored
dataPath = [userpath filesep 'Datasets']; % (e.g. /Users/myusername/Documents/MATLAB/Datasets)
cloudDatasetId = '67f723d574f5f79c6062389d';
datasetPath = fullfile(dataPath,cloudDatasetId);
% Download or load the NDI dataset 
% The first time you try to access the data, it needs to be downloaded from 
% NDI-cloud. This may take a few minutes. Once you have the dataset downloaded, 
% every other time you examine the data you can just load it.

if isfolder(datasetPath)
    % Load if already downloaded
    dataset = ndi.dataset.dir(datasetPath);
else
    % Download
    if ~isfolder(dataPath), mkdir(dataPath); end
    dataset = ndi.cloud.downloadDataset(cloudDatasetId,dataPath);
end
% Retrieve the NDI session
% A dataset can have multiple sessions, but this dataset has only one. We must 
% retrieve it in order to access the accompanying experimental *probes* (i.e. 
% a virtual or physical instrument that makes a measurement of or produces a stimulus 
% for a *subject*).

% Retrieve the session from this dataset
[session_ref_list,session_list] = dataset.session_list();
session = dataset.open_session(session_list{1});
% View NDI file types
% Each NDI *dataset* is composed of .json documents and associated binary files. 
% Let's start by taking a look at the *document* types in this *dataset*. We'll 
% subsequently explore each of these below.

[docTypes,docCounts] = ndi.fun.doc.getDocTypes(dataset);
documentsNDI = table(docTypes,docCounts)
%% Summarize subjects
% Each individual animal is referred to as a *subject* and has a unique alphanumeric 
% |SubjectDocumentIdentifier| and |SubjectLocalIdentifier|. This dataset contains 
% metadata about each *subject* including their species, strain, genetic strain 
% type, and biological sex which are linked to well-defined ontologies such as 
% NCBI and WormBase. Additionally, this dataset contains metadata about any *treatments* 
% that a *subject* received such as exposure to odorants, heat, or other chemicals. 
% A summary table showing the metadata for each *subject* can be viewed below.

% Get subject table and parse FigureName / ColumnName
subjectTable = ndi.fun.docTable.subject(session); % may take a minute
tokens = regexp(subjectTable.SubjectLocalIdentifier, ...
    '^Fig([^_]+)_(.+)_[^_]+$','tokens','once');
subjectTable.FigureName = cellfun(@(t) t{1},tokens,'UniformOutput',false);
subjectTable.ColumnName = cellfun(@(t) t{2},tokens,'UniformOutput',false);
subjectTable
%% Summarize figures
% Every |SubjectLocalIdentifier| encodes the paper panel and condition which 
% are summarized in the table below.

% Summarize data
figureNames = unique(subjectTable.FigureName);
columnNames = cellfun(@(f) strjoin(unique(subjectTable.ColumnName(strcmp(subjectTable.FigureName,f)),...
    'stable'),', '),figureNames,'UniformOutput',false);
figureTable = cell2table([figureNames,columnNames],'VariableNames',{'Figure','Conditions'});
figureTable = sortrows(figureTable,'Figure')
%% Retrieve data documents
% Analyzed data from this paper is stored in |ontologyTableRow| documents. Here, 
% we will retrieve these documents. Later, we will filter and view the documents 
% for *subject*(s) matching a given Figure and Condition.

% Get ontologyTableRow documents and their subject depedencies
queryDocType = ndi.query('','isa','ontologyTableRow');
dataTableDocs = session.database_search(queryDocType);
dataTableSubjectIDs = cellfun(@(d) d.dependency_value('document_id'), ...
    dataTableDocs,'UniformOutput',false);
%% Recapitulate a figure
% Here, we look at how to retrieve and plot data matching a given Figure from 
% the paper.

% Select a figure panel
figureNames = figureTable.Figure;
figureName = figureNames(21); figureName = figureName{1};

% Get subjects in this figure
indSubject = strcmp(subjectTable.FigureName,figureName);
figSubjectIDs = subjectTable.SubjectDocumentIdentifier(indSubject);

% Get data table rows in this figure
indData = ismember(dataTableSubjectIDs,figSubjectIDs);
[dataTable,~,~,dataSubjectIDs] = ndi.fun.doc.ontologyTableRowDoc2Table(dataTableDocs(indData),'StackAll',true);

% Add subject and column information
dataTable = addvars(dataTable{1},[dataSubjectIDs{1}{:}]',...
    'NewVariableNames','SubjectDocumentIdentifier');
dataTable = join(dataTable,subjectTable(:,{'SubjectDocumentIdentifier','ColumnName'}));

% Get experiment metadata
mixtureVariable = 'CElegansChemotaxisAssayParameter_ChemoattractantMixtureTable';
if ismember(mixtureVariable,dataTable.Properties.VariableNames)
    odorStruct = dataTable{:,mixtureVariable};
    odorTable = cellfun(@(mt) ndi.database.fun.readtablechar(mt,'.txt','Delimiter',','), ...
        odorStruct,'UniformOutput',false);
    odorTable = unique(ndi.fun.table.vstack(odorTable));
    figureSubtitle = sprintf('%d minute chemotaxis to %d μL %d%s %s',...
        unique(dataTable.CElegansChemotaxisAssayParameter_AssayDuration),...
        unique(dataTable.CElegansChemotaxisAssayParameter_ChemoattractantMixtureVolume),...
        odorTable.value, regexprep(odorTable.unitName{1},'Percent Volume per Volume','% v/v'),...
        odorTable.name{1});
elseif ismember('FluorescenceTargetName',dataTable.Properties.VariableNames)
    figureSubtitle = sprintf('%s fluorescence',dataTable.FluorescenceTargetName{1});
end

% Get plotting variable for this figure
plotVariables = {'CElegansChemotaxisAssayMeasurement_McCutcheonIndex',...
    'CElegansChemotaxisAssayMeasurement_MeanVelocity',...
    'FluorescentPunctalCount','MeanFluorescenceIntensity'};
variableName = intersect(plotVariables,dataTable.Properties.VariableNames);
variableName = variableName{1};

% Get list of all variables
[~,variableNames,ontologyNodes] = ndi.fun.doc.ontologyTableRowVars(dataTableDocs(indData));

% Look up the plotting variable in the ontology
termID = ontologyNodes{strcmp(variableNames,variableName)};
[id,name,~,definition,~,shortName] = ndi.ontology.lookup(termID);

% Display the variable's id, name, definition, and short name
variableInfo = cell2table({id,name,definition,shortName}',...
    'RowNames',{'ontology id','name','definition','variable name'},...
    'VariableNames',{'value'});

% Plot data
if ~isempty(variableName)
    x = categorical(dataTable.ColumnName);
    y = dataTable.(variableName);
    figure; violinplot(y,x);
    ylabel(name,'Interpreter','none');
    set(gca, 'TickLabelInterpreter', 'none');
    title(sprintf('Figure %s: %s',figureName,figureSubtitle));
end
variableInfo
%% Inspect a condition
% Pick one column from your chosen figure to see the *treatment* schedule plotted 
% as a Gantt chart, any microscopy videos, and any auxiliary files (plasmid maps, 
% LC-MS spectra) attached to this condition or to the strains it uses. The cell 
% below resolves the condition's |subject_group|, picks one representative *subject* 
% from it, and enumerates the document types attached.

% Select a condition
columnNames = unique(dataTable.ColumnName);
columnName = columnNames(3); columnName = columnName{1};

% Get subjects in this figure
indCondition = strcmp(subjectTable.FigureName,figureName) & ...
         strcmp(subjectTable.ColumnName,columnName);
conditionSubjectIDs = subjectTable.SubjectDocumentIdentifier(indCondition);
subject_id = conditionSubjectIDs{1};

% Find the condition-specific subject_group (one figure x one column)
candidateGroups = session.database_search(...
    ndi.query('','isa','subject_group') & ...
    ndi.query('','depends_on','',subject_id));
conditionGroupDoc = [];
for i = 1:numel(candidateGroups)
    subjectsInGroup = {candidateGroups{i}.document_properties.depends_on.value};
    rowInd = ismember(subjectTable.SubjectDocumentIdentifier,subjectsInGroup);
    if all(strcmp(regexprep(subjectTable.FigureName(rowInd), '\d+$', ''), ...
            regexprep(figureName, '\d+$', ''))) && ...
            isscalar(unique(subjectTable.ColumnName(rowInd)))
        conditionGroupDoc = candidateGroups{i};
        break;
    end
end
% Treatment ("training") timeline
% Each *subject* has one or more |treatment_drug| and |treatment_transfer| documents 
% that record the training and testing it received. The cell below plots those 
% as a Gantt chart for the representative *subject* chosen above.

% Get the treatment_drug documents for this subject
queryDocType = ndi.query('','isa','treatment_drug');
queryDependency = ndi.query('','depends_on','subject_id',subject_id);
treatmentDocs = session.database_search(queryDocType & queryDependency);

% Format metadata into a treatment table
treatmentStruct = cellfun(@(doc) doc.document_properties.treatment_drug, ...
    treatmentDocs,'UniformOutput',false);
treatmentStruct = [treatmentStruct{:}];
mixtureTable = cellfun(@(mt) ndi.database.fun.readtablechar(mt,'.txt','Delimiter',','), ...
    {treatmentStruct.mixture_table},'UniformOutput',false);
for i = 1:numel(mixtureTable)
    tempTable = struct2table(rmfield(treatmentStruct(i),'mixture_table'));
    tempTable = repmat(tempTable,height(mixtureTable{i}),1);
    tempTable = convertvars(tempTable, @(x) ischar(x) || isstring(x), 'cellstr');
    mixtureTable{i} = [mixtureTable{i},tempTable];
end
treatmentTable = ndi.fun.table.vstack(mixtureTable);
treatmentTable = convertvars(treatmentTable,{'administration_onset_time','administration_offset_time'}, ...
    @(x) duration(x,'InputFormat','hh:mm:ss'));
treatmentTable = convertvars(treatmentTable,'administration_duration',@days);
treatmentTable.administration_duration.Format = 'm';
treatmentTable
% Build condition labels (value + unit + name) for Gantt grouping
if ismember('value',treatmentTable.Properties.VariableNames)
    valStr = string(treatmentTable.value);
    valStr(isnan(treatmentTable.value)) = "";
    unitStr = string(treatmentTable.unitName);
    unitStr(unitStr == " " | ismissing(unitStr)) = "";
    unitStr = regexprep(unitStr,'Degree Celsius','C');
    unitStr = regexprep(unitStr,'Percent Volume per Volume','% v/v');
    unitStr = regexprep(unitStr,'Molar','M');
else
    valStr = strings(height(treatmentTable),1); unitStr = valStr;
end
groupNames = strtrim(valStr + " " + unitStr + " " + string(treatmentTable.name));
groupNames = strrep(groupNames,"  "," ");
[groupIDs,uniqueLabels] = findgroups(groupNames);
nGroups = numel(uniqueLabels);

% Draw the Gantt chart
figure('Color','w','Position',[100,100,900,500]); hold on;
colors = lines(nGroups);
for i = 1:height(treatmentTable)
    gID = groupIDs(i);
    x_coords = [treatmentTable.administration_onset_time(i), ...
                treatmentTable.administration_offset_time(i), ...
                treatmentTable.administration_offset_time(i), ...
                treatmentTable.administration_onset_time(i)];
    y_coords = [gID-0.3, gID-0.3, gID+0.3, gID+0.3];
    patch(x_coords,y_coords,colors(gID,:),'EdgeAlpha',0,'LineWidth',1);
end
title('Treatment Timeline','FontSize',14);
xlabel('Time (relative to assay)','FontSize',12);
ylabel('Treatment','FontSize',12);
yticks(1:nGroups); yticklabels(uniqueLabels);
ylim([0.5 nGroups+0.5]);
xline(hours(0),'REPLACE_WITH_DASH_DASHr','assay start','LineWidth',1, ...
    'LabelVerticalAlignment','bottom','FontSize',10);

% Overlay treatment_transfer events on the Gantt chart
queryType = ndi.query('','isa','treatment_transfer');
queryDependency  = ndi.query('','depends_on','recipient_id',subject_id);
transferDocs = session.database_search(queryType & queryDependency);

for i = 1:numel(transferDocs)
    transferInfo = transferDocs{i}.document_properties.treatment_transfer;

    % Get donor, method, and entity labels
    donor_id = transferDocs{i}.dependency_value('donor_id');
    donorDoc = session.database_search(ndi.query('base.id','exact_string',donor_id));
    if isempty(donorDoc)
        donorLabel = 'N/A';
    else
        if strcmp(donorDoc{1}.document_properties.document_class.class_name,'subject_group')
            subject_id = donorDoc{1}.dependency_value_n('subject_id');
        elseif strcmp(donorDoc{1}.document_properties.document_class.class_name,'subject')
            subject_id = donorDoc{1}.id;
        end
        indSubject = ismember(subjectTable.SubjectDocumentIdentifier,subject_id);
        donorLabel = sprintf('%s %s', ...
            subjectTable.FigureName{find(indSubject,1)}, ...
            subjectTable.ColumnName{find(indSubject,1)});
    end
    methodLabel = erase(string(transferInfo.method_name),'C. elegans transfer method: ');
    entityLabel =  replace(transferInfo.entity_name,' medium','');

    % Draw a dashed blue line at the transfer timestamp with donor + method
    xline(seconds(transferInfo.timestamp), 'REPLACE_WITH_DASH_DASHb', ...
        sprintf('transfered with %s to %s donated by %s', methodLabel,entityLabel,donorLabel), ...
        'LineWidth',1, 'FontSize',10,'LabelVerticalAlignment','bottom');
end
% Microscopy images / behavior videos
% |imageStack| documents hold fluorescence microscopy images and behavioral 
% assay videos attached to the chosen condition. The first cell below builds a 
% metadata table of what is available; the second shows the a single image or 
% video frame.

% Get imageStack documents
queryDocType = ndi.query('','isa','imageStack');
queryDependency = ndi.query('','depends_on','',conditionGroupDoc.id);
imageStackDocs = session.database_search(queryDocType & queryDependency);

% Create imageStack metadata table
imageStackParameters = cell(size(imageStackDocs));
for i = 1:numel(imageStackDocs)
    % Query ontologyLabel documents (used to label imageStack)
    queryDocType = ndi.query('','isa','ontologyLabel');
    queryDependency = ndi.query('','depends_on','',imageStackDocs{i}.id);
    labelDoc = session.database_search(queryDocType & queryDependency); % only one
    imageTerm = labelDoc{1}.document_properties.ontologyLabel.ontologyNode;
    [id,name,~,definition,~,shortName] = ndi.ontology.lookup(imageTerm);
    formatTerm = imageStackDocs{i}.document_properties.imageStack.formatOntology;
    [~,~,~,~,format] = ndi.ontology.lookup(formatTerm); format = lower(format{1});
    label = cell2table({id,name,definition,shortName,format},...
        'VariableNames',{'id','name','definition','shortName','format'});
    metadata = vlt.data.flattenstruct2table(imageStackDocs{i}.document_properties.imageStack_parameters);
    imageStackParameters{i} = [label,metadata];
end
if ~isempty(imageStackParameters)
    imageStackParameters = ndi.fun.table.vstack(imageStackParameters);
    imageStackParameters = convertvars(imageStackParameters,'timestamp',@(t) datetime(t,'ConvertFrom','datenum'))
end
if isempty(imageStackDocs)
    fprintf('No images or videos for Figure %s %s',figureName,columnName)
else
    % Choose an image/video
    imageNums = 1:numel(imageStackDocs);
    indImage = imageNums(1);
    imageFormat = strtok(imageStackParameters.format{indImage});

    % Get image/video data
    doc = imageStackDocs{indImage};
    [imageStack,imageStack_info] = ndi.fun.data.readImageStack(session,doc,imageFormat);
    if isa(imageStack,'VideoReader')
        image = read(imageStack,1); % first frame
    else
        image = imageStack;
    end

    % Plot image or play video
    figure;
    im = imshow(flip(image));  hold on;
    if ismatrix(image)
        clim(prctile(image,[0 100],'all'))
    end
end
% Plasmid maps / LC-MS tables
% |generic_file| documents hold auxiliary files — SnapGene plasmid maps (|.dna|) 
% for transgenic strains, Excel LC-MS spreadsheets (|.xlsx|) for mass-spec assays. 
% The first cell lists what is attached; the second opens one. If this condition 
% has no files, both cells are no-ops.

% Get generic_file documents
queryDocType = ndi.query('','isa','generic_file');
genericFileDocs = session.database_search(queryDocType);
genericFileSubjectGroups = cellfun(@(d) d.dependency_value('document_id'), ...
    genericFileDocs,'UniformOutput',false);
indFile = ismember(genericFileSubjectGroups,cellfun(@(d) d.id,candidateGroups,'UniformOutput',false));
genericFileDocs = genericFileDocs(indFile);

% Create generic_file metadata table
genericFileParameters = cell(size(genericFileDocs));
for i = 1:numel(genericFileDocs)
    % Query ontologyLabel documents (used to label imageStack)
    queryDocType = ndi.query('','isa','ontologyLabel');
    queryDependency = ndi.query('','depends_on','',genericFileDocs{i}.id);
    labelDoc = session.database_search(queryDocType & queryDependency); % only one
    fileTerm = labelDoc{1}.document_properties.ontologyLabel.ontologyNode;
    [id,name,~,definition,~,shortName] = ndi.ontology.lookup(fileTerm);
    formatTerm = genericFileDocs{i}.document_properties.generic_file.formatOntology;
    [~,format] = ndi.ontology.lookup(formatTerm);
    label = cell2table({id,name,definition,shortName,format},...
        'VariableNames',{'id','name','definition','shortName','format'});
    metadata = vlt.data.flattenstruct2table(genericFileDocs{i}.document_properties.generic_file);
    genericFileParameters{i} = [label,removevars(metadata,'formatOntology')];
end
if ~isempty(genericFileParameters)
    genericFileParameters = ndi.fun.table.vstack(genericFileParameters);
    genericFileParameters = convertvars(genericFileParameters,{'dateCreated','dateUpdated'},@(t) datetime(t,'ConvertFrom','datenum'))
end
if isempty(genericFileDocs)
    fprintf('No plasmid or LC-MS files for Figure %s %s',figureName,columnName)
else
    % Choose a file
    fileNums = 1:numel(genericFileDocs);
    indFile = fileNums(1);

    % Choose an export folder if you'd like to download the file locally and
    % open in another program (e.g. SnapGene or Excel)
    exportFolder = "";

    % Get file
    fileInfo = genericFileDocs{indFile}.document_properties.files.file_info;
    fileObj = dataset.database_openbinarydoc(genericFileDocs{indFile},fileInfo.name);
    [~,exportFileName,exportFileExt] = fileparts(genericFileDocs{indFile}.document_properties.generic_file.filename);

    % Download file to export folder (if requested)
    if ~isempty(exportFolder)
        currentFilePath = fileObj.fullpathfilename;
        exportFilePath = fullfile(exportFolder,[exportFileName,exportFileExt]);
        status = copyfile(currentFilePath,exportFilePath);
    end

    % Display data
    if strcmp(exportFileExt,'.dna')
        [dnaSeq,featureTable] = ndi.fun.data.plotSnapGeneMap(fileObj.fullpathfilename)
    elseif strcmp(exportFileExt,'.xlsx')
        lcmsTable = readtable(fileObj.fullpathfilename);
    end
    dataset.database_closebinarydoc(fileObj);
end
