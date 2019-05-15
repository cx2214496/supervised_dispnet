% Usage: copy to raw data directory along with toolbox files (inside of 'tools' subdirectory)

addpath('tools');

d = dir('.');
isub = [d(:).isdir]; %# returns logical vector
nameFolds = {d(isub).name}';
nameFolds(ismember(nameFolds,{'.','..','tools'})) = [];
nameFolds(ismember(nameFolds,{'_rgb','_depth','_mask'})) = [];% remove existing out folder if want to continue script before
nameFolds(~cellfun(@isempty,(regexp(nameFolds,'._out')))) = [];
disp(numel(nameFolds));

count = 0;
dist = 5;% I think that the original 40 is too big 

rgbOutFolder = '_rgb';
if ~exist(rgbOutFolder, 'dir')
	mkdir(rgbOutFolder);
end

depthOutFolder = '_depth';
if ~exist(depthOutFolder, 'dir')
	mkdir(depthOutFolder);
end

maskOutFolder = '_mask';
if ~exist(maskOutFolder, 'dir')
	mkdir(maskOutFolder);
end

%filledDepthOutFolder = '_filled';
%if ~exist(filledDepthOutFolder, 'dir')
%	mkdir(filledDepthOutFolder);
%end

for f = 1:numel(nameFolds)%1:347 no problem but 348-350 is empty
	disp(nameFolds{f});
	files = get_synched_frames(nameFolds{f});
        c = numel(files);
    disp(f);% show f avoid covering by sync frame information
	disp(strcat('filecount: ',int2str(c)));
    
	files = files(1:dist:c);%this dist is for choosing only pictures with time difference which make the final files consists of only 7000 pics
	c = numel(files);
	disp(strcat('filecount to process: ',int2str(c)));
    
    if isfield(files(1),'rawRgbFilename')
		parfor idx = 1:c
		    rgbFilename = strcat(nameFolds{f},'/',files(idx).rawRgbFilename);
		    depthFilename = strcat(nameFolds{f},'/',files(idx).rawDepthFilename);
		    outRGBFilename = strcat(rgbOutFolder,'/',num2str(count + idx - 1),'.png');
		    outDepthFilename = strcat(depthOutFolder,'/',num2str(count + idx - 1),'.png');
		    maskOutFilename = strcat(maskOutFolder,'/',num2str(count + idx - 1),'.png');
		    %filledDepthFilename = strcat(filledDepthOutFolder,'/',num2str(count + idx - 1),'.pgm');
		    rgb = imread(rgbFilename);
		    depth = imread(depthFilename);
		    depth = swapbytes(depth);
		    [depthOut, rgbOut] = project_depth_map(depth, rgb);
	   	    imgDepth = fill_depth_colorization(double(rgbOut) / 255.0, depthOut, 0.8);
		    %imgDepth = depthOut;
		    imgDepth = imgDepth / 10.0; %I don't think that we need this, but due to the multiplication in nyud_raw_train.py, we do not change here
		    imgDepth = crop_image(imgDepth);
		    rgbOut = crop_image(rgbOut);
		    maskOut = double(~(imgDepth == 0 | imgDepth == 1.0));

		    %filledImgDepth = filledImgDepth / 10.0;
		    %filledImgDepth = crop_image(filledImgDepth);

		    imwrite(rgbOut, outRGBFilename);
            %imwrite(imgDepth, outDepthFilename);
		    imwrite(uint16(round(imgDepth*65535)), outDepthFilename);
		    imwrite(maskOut, maskOutFilename);
		    %imwrite(filledImgDepth, filledDepthFilename);

		end
    end
	count = count + c;
end
disp(count);

exit;
