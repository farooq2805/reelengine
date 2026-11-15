import { Composition } from "remotion";
import { StyleReel, EditProps, totalFrames } from "./StyleReel";

// Example props so `npm run studio` opens something; real edits pass --props=props/<name>.json
const example: EditProps = {
  fps: 30,
  clips: [],
  words: [],
  style: {},
};

export const Root = () => (
  <Composition
    id="StyleReel"
    component={StyleReel}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={90}
    defaultProps={example}
    calculateMetadata={({ props }) => ({
      fps: props.fps || 30,
      durationInFrames: Math.max(totalFrames(props), 30),
    })}
  />
);
