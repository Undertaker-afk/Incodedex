import { make_dog } from './pkg/service';
class Base {}
class Widget extends Base {
  render() { return draw(this.x); }
}
function draw(x) { return x; }
function main() { return make_dog(); }
