import { Route, Switch } from "wouter";
import Index from "./pages/index";

function App() {
  return (
    <Switch>
      <Route path="/" component={Index} />
    </Switch>
  );
}

export default App;
