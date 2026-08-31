SELECT count(*)
FROM aka_title, complete_cast, movie_companies, movie_info, movie_keyword, movie_link, title
WHERE aka_title.season_nr = 1
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
