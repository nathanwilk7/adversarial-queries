SELECT count(*)
FROM cast_info, complete_cast, keyword, link_type, movie_keyword, movie_link, name, person_info, title
WHERE name.gender = 'm'
  AND title.production_year < 2006
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
