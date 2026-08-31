SELECT count(*)
FROM aka_title, cast_info, complete_cast, link_type, movie_info, movie_link, role_type, title
WHERE aka_title.production_year = 2003
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
